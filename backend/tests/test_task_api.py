import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.api.dependencies import get_task_repository
from app.db.models import TaskRecord
from app.main import app
from app.tasks import Task, TaskStatus
from app.tasks.repository import TaskRepository


@pytest.fixture
def repository() -> Mock:
    return Mock(spec=TaskRepository)


@pytest.fixture
def client(repository: Mock) -> Iterator[TestClient]:
    app.dependency_overrides[get_task_repository] = lambda: repository
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_get_existing_pending_task_returns_dto(
    client: TestClient,
    repository: Mock,
) -> None:
    task = Task(input="查询中的任务")
    repository.get.return_value = task

    response = client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(task.id)
    assert payload["status"] == "pending"
    assert payload["input"] == "查询中的任务"
    assert payload["result"] is None
    assert payload["error"] is None
    assert datetime.fromisoformat(payload["created_at"]) == task.created_at
    assert datetime.fromisoformat(payload["updated_at"]) == task.updated_at
    repository.get.assert_called_once_with(task.id)


def test_get_existing_succeeded_task_returns_result(
    client: TestClient,
    repository: Mock,
) -> None:
    task = Task(input="成功任务")
    task.start()
    task.succeed("96")
    repository.get.return_value = task

    response = client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["result"] == "96"
    assert response.json()["error"] is None


def test_get_existing_failed_task_returns_safe_error(
    client: TestClient,
    repository: Mock,
) -> None:
    task = Task(input="失败任务")
    task.start()
    task.fail("LLM provider request failed.")
    repository.get.return_value = task

    response = client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["result"] is None
    assert response.json()["error"] == "LLM provider request failed."


def test_get_missing_task_returns_404(
    client: TestClient,
    repository: Mock,
) -> None:
    repository.get.return_value = None

    response = client.get(f"/api/tasks/{uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found."}


def test_get_task_rejects_invalid_uuid(
    client: TestClient,
    repository: Mock,
) -> None:
    response = client.get("/api/tasks/not-a-uuid")

    assert response.status_code == 422
    repository.get.assert_not_called()


def test_list_tasks_uses_default_pagination(client: TestClient, repository: Mock) -> None:
    task = Task(input="list me")
    repository.list.return_value = [task]

    response = client.get("/api/tasks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 20
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["id"] == str(task.id)
    assert item["status"] == "pending"
    assert item["input"] == "list me"
    assert item["result"] is None
    assert item["error"] is None
    assert datetime.fromisoformat(item["created_at"]) == task.created_at
    assert datetime.fromisoformat(item["updated_at"]) == task.updated_at
    repository.list.assert_called_once_with(limit=20, offset=0)


def test_list_tasks_accepts_custom_pagination(client: TestClient, repository: Mock) -> None:
    repository.list.return_value = []

    response = client.get("/api/tasks?limit=2&offset=3")

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 2, "offset": 3}
    repository.list.assert_called_once_with(limit=2, offset=3)


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1"])
def test_list_tasks_rejects_invalid_pagination(
    client: TestClient, repository: Mock, query: str
) -> None:
    response = client.get(f"/api/tasks?{query}")

    assert response.status_code == 422
    repository.list.assert_not_called()


def test_list_tasks_returns_empty_items(client: TestClient, repository: Mock) -> None:
    repository.list.return_value = []

    response = client.get("/api/tasks")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_list_tasks_response_has_no_total_field(client: TestClient, repository: Mock) -> None:
    repository.list.return_value = []

    response = client.get("/api/tasks")

    assert set(response.json()) == {"items", "limit", "offset"}


def test_list_tasks_accepts_failed_status(client: TestClient, repository: Mock) -> None:
    repository.list.return_value = []

    response = client.get("/api/tasks?status=failed")

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 20, "offset": 0}
    repository.list.assert_called_once_with(
        limit=20,
        offset=0,
        status=TaskStatus.FAILED,
    )


def test_list_tasks_accepts_succeeded_status(client: TestClient, repository: Mock) -> None:
    repository.list.return_value = []

    response = client.get("/api/tasks?status=succeeded")

    assert response.status_code == 200
    repository.list.assert_called_once_with(
        limit=20,
        offset=0,
        status=TaskStatus.SUCCEEDED,
    )


def test_list_tasks_rejects_unknown_status(client: TestClient, repository: Mock) -> None:
    response = client.get("/api/tasks?status=unknown")

    assert response.status_code == 422
    repository.list.assert_not_called()


def test_list_tasks_passes_status_and_pagination(client: TestClient, repository: Mock) -> None:
    repository.list.return_value = []

    response = client.get("/api/tasks?status=failed&limit=2&offset=1")

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 2, "offset": 1}
    repository.list.assert_called_once_with(
        limit=2,
        offset=1,
        status=TaskStatus.FAILED,
    )


def test_list_tasks_returns_empty_filtered_result(client: TestClient, repository: Mock) -> None:
    repository.list.return_value = []

    response = client.get("/api/tasks?status=failed")

    assert response.status_code == 200
    assert response.json()["items"] == []


def _task_with_status(task_id: UUID, status: TaskStatus, created_at: datetime) -> Task:
    task = Task(
        id=task_id,
        input=f"task-{task_id.int}",
        created_at=created_at,
        updated_at=created_at,
    )
    if status is TaskStatus.SUCCEEDED:
        task.start(now=created_at)
        task.succeed("done", now=created_at)
    elif status is TaskStatus.FAILED:
        task.start(now=created_at)
        task.fail("failed", now=created_at)
    return task


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    from sqlalchemy import create_engine

    test_engine = create_engine(database_url)
    with test_engine.connect() as connection:
        assert inspect(connection).has_table("tasks")
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def integration_client(engine: Engine) -> Iterator[TestClient]:
    def override_task_repository() -> Iterator[TaskRepository]:
        with Session(engine) as session:
            yield TaskRepository(session)

    app.dependency_overrides[get_task_repository] = override_task_repository
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        with Session(engine) as session:
            session.execute(delete(TaskRecord))
            session.commit()


def test_get_task_reads_repository_data_from_postgresql(
    engine: Engine,
    integration_client: TestClient,
) -> None:
    task = Task(input="PostgreSQL query integration")
    task.start(now=task.updated_at + timedelta(seconds=1))
    task.succeed("96", now=task.updated_at + timedelta(seconds=1))
    with Session(engine) as session:
        TaskRepository(session).save(task)

    response = integration_client.get(f"/api/tasks/{task.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(task.id)
    assert payload["status"] == "succeeded"
    assert payload["input"] == "PostgreSQL query integration"
    assert payload["result"] == "96"
    assert payload["error"] is None
    assert (
        datetime.fromisoformat(payload["created_at"]).utcoffset()
        == timedelta(0)
    )
    assert (
        datetime.fromisoformat(payload["updated_at"]).utcoffset()
        == timedelta(0)
    )


def test_list_tasks_reads_paginated_data_from_postgresql(
    engine: Engine,
    integration_client: TestClient,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tasks = [
        Task(id=UUID(int=1), input="first", created_at=base, updated_at=base),
        Task(id=UUID(int=2), input="second", created_at=base, updated_at=base),
        Task(id=UUID(int=3), input="third", created_at=base, updated_at=base),
    ]
    with Session(engine) as session:
        repository = TaskRepository(session)
        for task in tasks:
            repository.save(task)

    first_page = integration_client.get("/api/tasks?limit=2&offset=0")
    second_page = integration_client.get("/api/tasks?limit=2&offset=2")

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    first_ids = [item["id"] for item in first_page.json()["items"]]
    second_ids = [item["id"] for item in second_page.json()["items"]]
    assert first_ids == [str(tasks[2].id), str(tasks[1].id)]
    assert second_ids == [str(tasks[0].id)]
    assert set(first_ids).isdisjoint(second_ids)


def test_list_tasks_filters_status_in_postgresql(
    engine: Engine,
    integration_client: TestClient,
) -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    failed_tasks = [
        _task_with_status(UUID(int=101), TaskStatus.FAILED, base),
        _task_with_status(UUID(int=102), TaskStatus.FAILED, base),
        _task_with_status(UUID(int=103), TaskStatus.FAILED, base),
    ]
    succeeded_task = _task_with_status(UUID(int=104), TaskStatus.SUCCEEDED, base)
    with Session(engine) as session:
        repository = TaskRepository(session)
        for task in [*failed_tasks, succeeded_task]:
            repository.save(task)

    failed_first_page = integration_client.get(
        "/api/tasks?status=failed&limit=2&offset=0"
    )
    failed_second_page = integration_client.get(
        "/api/tasks?status=failed&limit=2&offset=2"
    )
    succeeded_page = integration_client.get("/api/tasks?status=succeeded")

    assert failed_first_page.status_code == 200
    assert failed_second_page.status_code == 200
    assert succeeded_page.status_code == 200
    assert [item["id"] for item in failed_first_page.json()["items"]] == [
        str(failed_tasks[2].id),
        str(failed_tasks[1].id),
    ]
    assert [item["id"] for item in failed_second_page.json()["items"]] == [
        str(failed_tasks[0].id)
    ]
    assert all(
        item["status"] == "failed"
        for item in failed_first_page.json()["items"]
        + failed_second_page.json()["items"]
    )
    assert [item["id"] for item in succeeded_page.json()["items"]] == [
        str(succeeded_task.id)
    ]

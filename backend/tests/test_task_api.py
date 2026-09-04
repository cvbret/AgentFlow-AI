import os
from collections.abc import Iterator
from datetime import datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

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

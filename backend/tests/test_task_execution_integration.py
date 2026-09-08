import os
from collections.abc import Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.agents.runtime import AgentResult
from app.api.dependencies import get_agent_runtime_provider, get_db_session
from app.db.models import TaskRecord
from app.main import app
from app.llm.client import LLMProviderError


class FakeRuntime:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def run(self, messages, *, task_id):
        if self.error is not None:
            raise self.error
        return AgentResult(content="96")


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


@pytest.fixture(autouse=True)
def clean_tasks(engine: Engine) -> Iterator[None]:
    yield
    with Session(engine) as session:
        session.execute(delete(TaskRecord))
        session.commit()


def call_agent_api(engine: Engine, runtime: FakeRuntime, message: str):
    def override_db_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    app.dependency_overrides[get_agent_runtime_provider] = lambda: (
        lambda: runtime
    )
    try:
        with TestClient(app) as client:
            return client.post("/api/agent/run", json={"message": message})
    finally:
        app.dependency_overrides.clear()


def call_task_query_api(engine: Engine, task_id: UUID):
    def override_db_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db_session] = override_db_session
    try:
        with TestClient(app) as client:
            return client.get(f"/api/tasks/{task_id}")
    finally:
        app.dependency_overrides.clear()


def get_task_by_input(engine: Engine, message: str) -> TaskRecord:
    with Session(engine) as session:
        task = session.scalar(
            select(TaskRecord).where(TaskRecord.input == message)
        )
        assert task is not None
        return task


def test_api_success_persists_succeeded_task_in_postgresql(engine: Engine) -> None:
    response = call_agent_api(engine, FakeRuntime(), "integration success")

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "96"
    task_id = UUID(payload["task_id"])

    task = get_task_by_input(engine, "integration success")
    assert task.id == task_id
    assert task.status == "SUCCEEDED"
    assert task.result == "96"
    assert task.error is None

    query_response = call_task_query_api(engine, task_id)

    assert query_response.status_code == 200
    assert query_response.json()["id"] == payload["task_id"]
    assert query_response.json()["status"] == "succeeded"
    assert query_response.json()["result"] == payload["answer"]


def test_api_failure_persists_failed_task_in_postgresql(engine: Engine) -> None:
    runtime = FakeRuntime(LLMProviderError("provider secret and raw payload"))

    response = call_agent_api(engine, runtime, "integration failure")

    assert response.status_code == 502
    assert response.json() == {"detail": "LLM provider request failed."}
    assert "provider secret" not in response.text

    task = get_task_by_input(engine, "integration failure")
    assert task.status == "FAILED"
    assert task.result is None
    assert task.error == "LLM provider request failed."

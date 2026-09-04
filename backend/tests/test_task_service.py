from unittest.mock import Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.agents.runtime import AgentResult
from app.llm.client import LLMProviderError
from app.tasks import TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskExecutionService


class FakeRuntime:
    def __init__(self, result: str = "96", error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def run(self, messages):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return AgentResult(content=self.result)


def make_service(
    repository: Mock,
    runtime: FakeRuntime,
) -> TaskExecutionService:
    return TaskExecutionService(repository, lambda: runtime)


def make_recording_repository() -> tuple[
    Mock,
    list[tuple[TaskStatus, str | None, str | None]],
]:
    repository = Mock(spec=TaskRepository)
    snapshots: list[tuple[TaskStatus, str | None, str | None]] = []

    def save(task) -> None:
        snapshots.append((task.status, task.result, task.error))

    repository.save.side_effect = save
    return repository, snapshots


def test_execute_persists_pending_running_and_succeeded() -> None:
    repository, snapshots = make_recording_repository()
    runtime = FakeRuntime()

    task = make_service(repository, runtime).execute("calculate")

    assert snapshots == [
        (TaskStatus.PENDING, None, None),
        (TaskStatus.RUNNING, None, None),
        (TaskStatus.SUCCEEDED, "96", None),
    ]
    assert task.status is TaskStatus.SUCCEEDED
    assert task.result == "96"
    assert runtime.calls == 1


def test_agent_failure_persists_failed_and_reraises_original_error() -> None:
    repository, snapshots = make_recording_repository()
    error = LLMProviderError("provider secret and raw payload")
    runtime = FakeRuntime(error=error)

    with pytest.raises(LLMProviderError) as raised:
        make_service(repository, runtime).execute("calculate")

    assert raised.value is error
    assert snapshots == [
        (TaskStatus.PENDING, None, None),
        (TaskStatus.RUNNING, None, None),
        (TaskStatus.FAILED, None, "LLM provider request failed."),
    ]
    assert runtime.calls == 1


def test_failed_persistence_does_not_replace_agent_error() -> None:
    repository = Mock(spec=TaskRepository)
    agent_error = LLMProviderError("provider secret and raw payload")
    persistence_error = SQLAlchemyError("failed state save failed")
    repository.save.side_effect = [None, None, persistence_error]
    runtime = FakeRuntime(error=agent_error)

    with pytest.raises(LLMProviderError) as raised:
        make_service(repository, runtime).execute("calculate")

    assert raised.value is agent_error
    assert raised.value.__cause__ is persistence_error
    assert repository.save.call_count == 3


def test_initial_persistence_failure_does_not_execute_runtime() -> None:
    repository = Mock(spec=TaskRepository)
    repository.save.side_effect = SQLAlchemyError("initial save failed")
    runtime_provider = Mock()
    service = TaskExecutionService(repository, runtime_provider)

    with pytest.raises(SQLAlchemyError, match="initial save failed"):
        service.execute("calculate")

    runtime_provider.assert_not_called()


def test_running_persistence_failure_does_not_execute_runtime() -> None:
    repository = Mock(spec=TaskRepository)
    repository.save.side_effect = [
        None,
        SQLAlchemyError("running save failed"),
    ]
    runtime_provider = Mock()
    service = TaskExecutionService(repository, runtime_provider)

    with pytest.raises(SQLAlchemyError, match="running save failed"):
        service.execute("calculate")

    runtime_provider.assert_not_called()


def test_success_final_persistence_failure_propagates_database_error() -> None:
    repository = Mock(spec=TaskRepository)
    repository.save.side_effect = [
        None,
        None,
        SQLAlchemyError("final save failed"),
    ]
    runtime = FakeRuntime()

    with pytest.raises(SQLAlchemyError, match="final save failed"):
        make_service(repository, runtime).execute("calculate")

    assert runtime.calls == 1

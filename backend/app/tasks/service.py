from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError

from app.agents.runtime import AgentMaxStepsExceededError, AgentResult, AgentRuntime
from app.tasks.pause_persistence import HITLPausePersistence
from app.llm.client import (
    ConfigurationError,
    InvalidLLMResponseError,
    LLMProviderError,
)
from app.llm.schemas import ChatMessage
from app.protected_execution import ApprovalRequired
from app.tasks.models import Task
from app.tasks.repository import TaskRepository
from app.tools.exceptions import (
    ToolExecutionError,
    ToolInputValidationError,
    ToolNotFoundError,
)


_SAFE_EXECUTION_ERROR_MESSAGES: dict[type[Exception], str] = {
    ConfigurationError: "Agent configuration is unavailable.",
    LLMProviderError: "LLM provider request failed.",
    InvalidLLMResponseError: "LLM provider returned an invalid response.",
    AgentMaxStepsExceededError: "Agent execution exceeded the maximum step limit.",
    ToolNotFoundError: "Agent tool execution failed.",
    ToolInputValidationError: "Agent tool execution failed.",
    ToolExecutionError: "Agent tool execution failed.",
}


class TaskExecutionService:
    """Coordinate one Task's persistence and AgentRuntime execution."""

    def __init__(
        self,
        repository: TaskRepository,
        runtime_provider: Callable[[], AgentRuntime],
        pause_persistence: HITLPausePersistence,
    ) -> None:
        self._repository = repository
        self._runtime_provider = runtime_provider
        self._pause_persistence = pause_persistence

    def execute(self, task_input: str) -> Task:
        task = Task(input=task_input)
        self._repository.save(task)

        task.start()
        self._repository.save(task)

        return self.continue_running(task, lambda: self._runtime_provider().run(
            [ChatMessage(role="user", content=task_input)], task_id=task.id))

    def continue_running(self, task: Task, invoke: Callable[[], AgentResult]) -> Task:
        try:
            try:
                result = invoke()
            except ApprovalRequired as signal:
                waiting_task = Task.restore(**task.model_dump())
                waiting_task.mark_waiting_approval()
                self._pause_persistence.save(waiting_task, signal.approval)
                return waiting_task
        except Exception as exc:
            task.fail(
                _SAFE_EXECUTION_ERROR_MESSAGES.get(type(exc), "Agent execution failed.")
            )
            try:
                # Zero rows does not confirm any particular durable state.
                # Preserve the original error regardless of whether FAILED won.
                self._repository.save_failed_if_running(task)
            except SQLAlchemyError as persistence_error:
                raise exc from persistence_error
            raise

        task.succeed(result.content)
        self._repository.save(task)
        return task

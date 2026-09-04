from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError

from app.agents.runtime import AgentMaxStepsExceededError, AgentRuntime
from app.llm.client import (
    ConfigurationError,
    InvalidLLMResponseError,
    LLMProviderError,
)
from app.llm.schemas import ChatMessage
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

KNOWN_EXECUTION_ERRORS = tuple(_SAFE_EXECUTION_ERROR_MESSAGES)


class TaskExecutionService:
    """Coordinate one Task's persistence and AgentRuntime execution."""

    def __init__(
        self,
        repository: TaskRepository,
        runtime_provider: Callable[[], AgentRuntime],
    ) -> None:
        self._repository = repository
        self._runtime_provider = runtime_provider

    def execute(self, task_input: str) -> Task:
        task = Task(input=task_input)
        self._repository.save(task)

        task.start()
        self._repository.save(task)

        try:
            result = self._runtime_provider().run(
                [ChatMessage(role="user", content=task_input)]
            )
        except KNOWN_EXECUTION_ERRORS as exc:
            task.fail(_SAFE_EXECUTION_ERROR_MESSAGES[type(exc)])
            try:
                self._repository.save(task)
            except SQLAlchemyError as persistence_error:
                raise exc from persistence_error
            raise

        task.succeed(result.content)
        self._repository.save(task)
        return task

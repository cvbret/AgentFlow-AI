from collections.abc import Sequence

from pydantic import BaseModel

from app.llm.client import InvalidLLMResponseError, LLMClient
from app.llm.schemas import ChatMessage
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


DEFAULT_MAX_STEPS = 5


class AgentError(RuntimeError):
    """Base error for the Agent runtime."""


class AgentMaxStepsExceededError(AgentError):
    """Raised when the Agent does not produce a final answer in time."""


class AgentResult(BaseModel):
    content: str


class AgentRuntime:
    """Execute a bounded LLM and Tool loop."""

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        max_steps: int = DEFAULT_MAX_STEPS,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")

        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._tool_executor = ToolExecutor(tool_registry)
        self._max_steps = max_steps

    def close(self) -> None:
        self._llm_client.close()

    def run(self, initial_messages: Sequence[ChatMessage]) -> AgentResult:
        messages = list(initial_messages)
        tool_definitions = self._tool_registry.list()

        for _step in range(self._max_steps):
            response = self._llm_client.chat(
                messages=messages,
                tools=tool_definitions,
            )
            if not response.tool_calls:
                if response.content is None or not response.content.strip():
                    raise InvalidLLMResponseError(
                        "LLM response without tool_calls must contain non-empty content"
                    )
                return AgentResult(content=response.content)

            messages.append(
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            for tool_call in response.tool_calls:
                execution_result = self._tool_executor.execute(tool_call)
                messages.append(
                    ChatMessage(
                        role="tool",
                        tool_call_id=execution_result.tool_call_id,
                        content=execution_result.content,
                    )
                )

        raise AgentMaxStepsExceededError(
            f"Agent exceeded max_steps={self._max_steps}"
        )

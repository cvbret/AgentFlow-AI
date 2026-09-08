from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel

from app.agents.exceptions import AgentError, AgentMaxStepsExceededError
from app.llm.client import LLMClient
from app.llm.schemas import ChatMessage
from app.protected_execution import ProtectedToolExecutionService
from app.tools.registry import ToolRegistry


DEFAULT_MAX_STEPS = 5


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
        self._max_steps = max_steps

    def close(self) -> None:
        self._llm_client.close()

    def run(
        self,
        initial_messages: Sequence[ChatMessage],
        *,
        task_id: UUID,
    ) -> AgentResult:
        from app.workflows.agent import build_agent_graph

        protected_execution = ProtectedToolExecutionService(
            self._tool_registry
        )
        graph = build_agent_graph(
            self._llm_client,
            self._tool_registry.list(),
            protected_execution,
            max_steps=self._max_steps,
        )
        state = graph.invoke(
            {
                "task_id": str(task_id),
                "messages": list(initial_messages),
                "step_count": 0,
            },
            # Each round can visit LLM and Tool; leave room for the explicit
            # exhaustion check. This framework guard is not the step budget.
            config={"recursion_limit": 2 * self._max_steps + 2},
        )
        return AgentResult(content=state["final_answer"])

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.exceptions import AgentError, AgentMaxStepsExceededError
from app.approvals.models import Approval
from app.approved_execution import ApprovedToolExecutionService, ResumeAuthorizationError
from app.llm.client import LLMClient
from app.llm.schemas import ChatMessage, ToolCall
from app.protected_execution import ApprovalRequired, ProtectedToolExecutionService
from app.tools.registry import ToolRegistry
from app.workflows.graph import AgentGraphState


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
        *,
        checkpointer_factory: Callable[[], AbstractContextManager[BaseCheckpointSaver]] | None = None,
        approval_loader: Callable[[UUID], Approval | None] | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")

        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._max_steps = max_steps
        self._checkpointer_factory = checkpointer_factory
        self._approved_execution = (ApprovedToolExecutionService(tool_registry, approval_loader)
                                    if approval_loader is not None else None)

    def close(self) -> None:
        self._llm_client.close()

    def run(
        self,
        initial_messages: Sequence[ChatMessage],
        *,
        task_id: UUID,
    ) -> AgentResult:
        return self._invoke(task_id, {
            "task_id": str(task_id),
            "messages": [m.model_dump(mode="json") for m in initial_messages],
            "step_count": 0,
            "max_steps": self._max_steps,
        })

    def resume(self, *, task_id: UUID, approval_id: UUID) -> AgentResult:
        return self._invoke(task_id, None, approval_id=approval_id)

    def _invoke(self, task_id: UUID, initial_state: AgentGraphState | None, *, approval_id: UUID | None = None) -> AgentResult:
        from app.workflows.agent import build_agent_graph

        context = self._checkpointer_factory() if self._checkpointer_factory else nullcontext(None)
        with context as saver:
            graph = build_agent_graph(self._llm_client, self._tool_registry.list(),
                ProtectedToolExecutionService(self._tool_registry), max_steps=self._max_steps,
                checkpointer=saver, approved_execution=self._approved_execution)
            config = {"configurable": {"thread_id": str(task_id)},
                      "recursion_limit": 2 * self._max_steps + 4}
            if approval_id is not None:
                if saver is None or self._approved_execution is None:
                    raise ResumeAuthorizationError("Durable resume is not configured")
                snapshot = graph.get_state(config)
                pending = snapshot.values.get("pending_approval")
                if (snapshot.next != ("approval_pause",) or not pending
                        or pending["id"] != str(approval_id)
                        or pending["task_id"] != str(task_id)
                        or snapshot.values.get("task_id") != str(task_id)):
                    raise ResumeAuthorizationError("No matching durable continuation")
                call = ToolCall.model_validate(snapshot.values["tool_calls"][snapshot.values["tool_cursor"]])
                self._approved_execution.validate(approval_id=approval_id, task_id=task_id, tool_call=call)
                config["recursion_limit"] = 2 * snapshot.values["max_steps"] + 4
                invocation = Command(resume={"task_id": str(task_id), "approval_id": str(approval_id)})
            else:
                if saver is not None and graph.get_state(config).values:
                    raise ResumeAuthorizationError("Task workflow already exists")
                invocation = initial_state
            options = {"durability": "sync"} if saver is not None else {}
            state = graph.invoke(invocation, config=config, **options)
            # invoke exits only after synchronous checkpoint writes complete.
            if state.get("__interrupt__"):
                raise ApprovalRequired(Approval(**state["pending_approval"]))
            return AgentResult(content=state["final_answer"])

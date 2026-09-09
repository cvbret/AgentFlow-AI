from collections.abc import Callable, Sequence
from app.observability import emit, observation_context
from contextlib import AbstractContextManager, nullcontext, contextmanager
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command
from pydantic import BaseModel

from app.agents.exceptions import AgentError, AgentMaxStepsExceededError
from app.approvals.models import Approval
from app.approved_execution import ApprovedToolExecutionService, ResumeAuthorizationError
from app.executions.repository import ExecutionRepository
from app.executions.recovery import ExecutionRecoveryService
from app.workflows.recovery import WorkflowEvidence
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
        execution_repository: ExecutionRepository | None = None,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")

        self._llm_client = llm_client
        self._tool_registry = tool_registry
        self._max_steps = max_steps
        self._checkpointer_factory = checkpointer_factory
        self._execution_recovery = (ExecutionRecoveryService(tool_registry, approval_loader, execution_repository)
                                    if approval_loader is not None else None)
        self._approved_execution = (ApprovedToolExecutionService(tool_registry, approval_loader, execution_repository)
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
        with observation_context(task_id=task_id, thread_id=task_id):
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
                    emit("workflow.resumed", component="workflow", outcome="resumed", approval_id=approval_id, tool_call_id=call.id)
                    invocation = Command(resume={"task_id": str(task_id), "approval_id": str(approval_id)})
                else:
                    if saver is not None and graph.get_state(config).values:
                        raise ResumeAuthorizationError("Task workflow already exists")
                    invocation = initial_state
                options = {"durability": "sync"} if saver is not None else {}
                state = graph.invoke(invocation, config=config, **options)
                # invoke exits only after synchronous checkpoint writes complete.
                if state.get("__interrupt__"):
                    emit("workflow.paused", component="workflow", outcome="paused",
                         approval_id=state["pending_approval"]["id"], tool_call_id=state["pending_approval"]["tool_call_id"])
                    raise ApprovalRequired(Approval(**state["pending_approval"]))
                return AgentResult(content=state["final_answer"])

    @contextmanager
    def _recovery_graph(self, task_id: UUID):
        from app.workflows.agent import build_agent_graph
        if self._checkpointer_factory is None:
            raise ResumeAuthorizationError("Durable checkpoint access is not configured")
        with self._checkpointer_factory() as saver:
            graph = build_agent_graph(self._llm_client, self._tool_registry.list(),
                ProtectedToolExecutionService(self._tool_registry), max_steps=self._max_steps,
                checkpointer=saver, approved_execution=self._approved_execution)
            yield graph, {"configurable": {"thread_id": str(task_id)}}

    def workflow_evidence(self, task_id: UUID) -> WorkflowEvidence:
        with self._recovery_graph(task_id) as (graph, config):
            state = graph.get_state(config)
            identity = state.config.get("configurable", {}).get("checkpoint_id") if state.config else None
            return WorkflowEvidence(identity, state.next, state.values)

    def recovery_capability(self, tool_name: str):
        return self._tool_registry.get(tool_name).metadata().idempotency_mode

    def recover_execution(self, *, task_id, approval_id, tool_call, stale_before):
        if self._execution_recovery is None:
            raise ResumeAuthorizationError("Execution recovery is not configured")
        return self._execution_recovery.recover(task_id=task_id, approval_id=approval_id,
            tool_call=tool_call, stale_before=stale_before)

    def resume_pending_tool(self, *, task_id: UUID, approval_id: UUID, checkpoint_id: str) -> AgentResult:
        with observation_context(task_id=task_id, thread_id=task_id):
            with self._recovery_graph(task_id) as (graph, config):
                snapshot = graph.get_state(config)
                pending = snapshot.values.get("pending_approval")
                identity = snapshot.config.get("configurable", {}).get("checkpoint_id") if snapshot.config else None
                if (identity != checkpoint_id or snapshot.next != ("tool",) or not pending
                        or pending["id"] != str(approval_id) or pending["task_id"] != str(task_id)
                        or snapshot.values.get("task_id") != str(task_id)
                        or snapshot.values.get("resume_approval_id") != str(approval_id)):
                    raise ResumeAuthorizationError("Recovery checkpoint correlation changed")
                call = ToolCall.model_validate(snapshot.values["tool_calls"][snapshot.values["tool_cursor"]])
                self._approved_execution.validate(task_id=task_id, approval_id=approval_id, tool_call=call)
                config["recursion_limit"] = 2 * snapshot.values["max_steps"] + 4
                emit("workflow.resumed", component="workflow", outcome="resumed", approval_id=approval_id, tool_call_id=call.id)
                result = graph.invoke(None, config=config, durability="sync")
                if result.get("__interrupt__"):
                    emit("workflow.paused", component="workflow", outcome="paused",
                         approval_id=result["pending_approval"]["id"], tool_call_id=result["pending_approval"]["tool_call_id"])
                    raise ApprovalRequired(Approval(**result["pending_approval"]))
                return AgentResult(content=result["final_answer"])

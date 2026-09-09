"""Execution authorized by a persisted Approval, never by a resume boolean."""
from collections.abc import Callable
from uuid import UUID

from app.approvals.models import Approval, ApprovalStatus
from app.llm.schemas import ToolCall
from app.tools.registry import ToolRegistry
from app.tools.schemas import IdempotencyMode, ToolExecutionContext, ToolExecutionResult
from app.tools.exceptions import ToolExecutionFailedWithoutEffect, ToolExecutionOutcomeUnknown
from app.executions.models import ExecutionStatus, ToolExecution, canonical_arguments
from app.executions.repository import ExecutionRepository
from app.executions.exceptions import ExecutionIdentityConflict, ExecutionReplayBlocked


class ResumeAuthorizationError(RuntimeError):
    pass


class ApprovedToolExecutionService:
    def __init__(self, registry: ToolRegistry, load_approval: Callable[[UUID], Approval | None],
                 executions: ExecutionRepository | None = None):
        self._registry = registry
        self._executions = executions
        # Loader must read business persistence and close its transaction before returning.
        self._load_approval = load_approval

    def validate(self, *, approval_id: UUID, task_id: UUID, tool_call: ToolCall) -> Approval:
        approval = self._load_approval(approval_id)
        if (approval is None or approval.status is not ApprovalStatus.APPROVED
                or approval.id != approval_id or approval.task_id != task_id
                or approval.tool_call_id != tool_call.id or approval.tool_name != tool_call.name
                or canonical_arguments(approval.arguments) != canonical_arguments(tool_call.arguments)):
            raise ResumeAuthorizationError("Persisted Approval does not authorize this continuation")
        return approval

    def execute(self, *, approval_id: UUID, task_id: UUID, tool_call: ToolCall) -> ToolExecutionResult:
        self.validate(approval_id=approval_id, task_id=task_id, tool_call=tool_call)
        if self._executions is None:
            raise ExecutionReplayBlocked("Durable execution ledger is not configured")
        candidate = ToolExecution(task_id=task_id, approval_id=approval_id,
            tool_call_id=tool_call.id, tool_name=tool_call.name, arguments=tool_call.arguments)
        # An existing successful result does not depend on today's Tool schema.
        existing = self._executions.get(task_id, tool_call.id)
        if existing is not None:
            return self._replay(existing, candidate)
        tool = self._registry.get(tool_call.name)
        tool.validate_input(tool_call.arguments)  # Known pre-effect failure: no claim needed.
        execution, won = self._executions.claim(candidate)
        if not won:
            return self._replay(execution, candidate)
        return self._execute_claimed(tool, execution)

    def _execute_claimed(self, tool, execution):
        """Shared mechanics; entry points must first authorize and commit a claim."""
        tool_call = ToolCall(id=execution.tool_call_id, name=execution.tool_name, arguments=execution.arguments)
        try:
            if tool.metadata().idempotency_mode is IdempotencyMode.EXTERNAL_KEY:
                result = tool.execute(tool_call.arguments,
                    context=ToolExecutionContext(idempotency_key=execution.idempotency_key))
            else:
                result = tool.execute(tool_call.arguments)
        except ToolExecutionFailedWithoutEffect as exc:
            self._persist_failure(execution, ExecutionStatus.FAILED, "known_no_effect", exc)
            raise
        except Exception as exc:
            # Generic ToolExecutionError does not prove an external effect failed.
            self._persist_failure(execution, ExecutionStatus.UNKNOWN, "outcome_unknown", exc)
            if isinstance(exc, ToolExecutionOutcomeUnknown):
                raise
            raise ToolExecutionOutcomeUnknown("Tool execution outcome is uncertain") from exc
        # Persistence errors leave EXECUTING (or committed SUCCEEDED on lost ack).
        # Never retry Tool or guess FAILED when this write fails.
        self._executions.finish(execution.finish(ExecutionStatus.SUCCEEDED, result_content=result.content),
                                expected_updated_at=execution.updated_at)
        return ToolExecutionResult(tool_call_id=tool_call.id, tool_name=tool_call.name, content=result.content)

    def _persist_failure(self, execution, status, code, original):
        try:
            self._executions.finish(execution.finish(status, error_code=code),
                                    expected_updated_at=execution.updated_at)
        except Exception as persistence_error:
            raise original from persistence_error

    @staticmethod
    def _replay(execution: ToolExecution, candidate: ToolExecution) -> ToolExecutionResult:
        if (execution.task_id != candidate.task_id or execution.tool_call_id != candidate.tool_call_id
                or execution.approval_id != candidate.approval_id or execution.tool_name != candidate.tool_name
                or canonical_arguments(execution.arguments) != canonical_arguments(candidate.arguments)):
            raise ExecutionIdentityConflict("Execution identity has different authorization or Tool context")
        if execution.status is ExecutionStatus.SUCCEEDED:
            return ToolExecutionResult(tool_call_id=execution.tool_call_id,
                tool_name=execution.tool_name, content=execution.result_content)
        if execution.status is ExecutionStatus.UNKNOWN:
            raise ToolExecutionOutcomeUnknown("Stored execution outcome is uncertain; replay prohibited")
        raise ExecutionReplayBlocked(f"Execution is {execution.status.value}; automatic replay prohibited")

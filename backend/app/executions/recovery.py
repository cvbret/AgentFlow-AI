from datetime import datetime
from uuid import UUID

from app.approved_execution import ApprovedToolExecutionService
from app.executions.models import ExecutionStatus, canonical_arguments
from app.executions.exceptions import ExecutionIdentityConflict, ExecutionReplayBlocked
from app.llm.schemas import ToolCall
from app.tools.schemas import IdempotencyMode


class ExecutionRecoveryService(ApprovedToolExecutionService):
    """Explicit single recovery attempt; ordinary execute() remains fail closed."""
    def recover(self, *, task_id: UUID, approval_id: UUID, tool_call: ToolCall, stale_before: datetime):
        self.validate(task_id=task_id, approval_id=approval_id, tool_call=tool_call)
        if self._executions is None:
            raise ExecutionReplayBlocked("Recovery ledger is not configured")
        execution = self._executions.get(task_id, tool_call.id)
        if execution is None:
            raise ExecutionReplayBlocked("No execution to recover")
        if (execution.task_id != task_id or execution.approval_id != approval_id
                or execution.tool_call_id != tool_call.id or execution.tool_name != tool_call.name
                or canonical_arguments(execution.arguments) != canonical_arguments(tool_call.arguments)):
            raise ExecutionIdentityConflict("Recovery execution context mismatch")
        if execution.status is ExecutionStatus.SUCCEEDED:
            return self.execute(task_id=task_id, approval_id=approval_id, tool_call=tool_call)
        if execution.updated_at > stale_before:
            raise ExecutionReplayBlocked("Execution is still in progress")
        tool = self._registry.get(tool_call.name)
        if tool.metadata().idempotency_mode not in (IdempotencyMode.EXTERNAL_KEY, IdempotencyMode.INHERENT):
            raise ExecutionReplayBlocked("Tool has no safe recovery capability")
        claimed = self._executions.claim_recovery(execution, stale_before=stale_before)
        if claimed is None:
            raise ExecutionReplayBlocked("Recovery execution claim lost")
        return self._execute_claimed(tool, claimed)

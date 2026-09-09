"""Execution authorized by a persisted Approval, never by a resume boolean."""
import json
from collections.abc import Callable
from uuid import UUID

from app.approvals.models import Approval, ApprovalStatus
from app.llm.schemas import ToolCall
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolExecutionResult


class ResumeAuthorizationError(RuntimeError):
    pass


class ApprovedToolExecutionService:
    def __init__(self, registry: ToolRegistry, load_approval: Callable[[UUID], Approval | None]):
        self._registry = registry
        # Loader must read business persistence and close its transaction before returning.
        self._load_approval = load_approval

    def validate(self, *, approval_id: UUID, task_id: UUID, tool_call: ToolCall) -> Approval:
        approval = self._load_approval(approval_id)
        if (approval is None or approval.status is not ApprovalStatus.APPROVED
                or approval.id != approval_id or approval.task_id != task_id
                or approval.tool_call_id != tool_call.id or approval.tool_name != tool_call.name
                or json.dumps(approval.arguments, sort_keys=True) != json.dumps(tool_call.arguments, sort_keys=True)):
            raise ResumeAuthorizationError("Persisted Approval does not authorize this continuation")
        return approval

    def execute(self, *, approval_id: UUID, task_id: UUID, tool_call: ToolCall) -> ToolExecutionResult:
        self.validate(approval_id=approval_id, task_id=task_id, tool_call=tool_call)
        # Reuse Registry resolution and Tool.execute validation/error handling.
        tool = self._registry.get(tool_call.name)
        result = tool.execute(tool_call.arguments)
        return ToolExecutionResult(tool_call_id=tool_call.id, tool_name=tool_call.name, content=result.content)

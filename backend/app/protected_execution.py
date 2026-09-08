from uuid import UUID

from app.approvals.models import Approval
from app.llm.schemas import ToolCall
from app.tools.executor import ToolExecutor
from app.tools.policy import ToolExecutionPolicy
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolExecutionResult


class ApprovalRequired(RuntimeError):
    """Signal that a protected ToolCall needs human approval before execution."""

    def __init__(self, approval: Approval) -> None:
        # This is an internal request, not evidence of a durable pause.
        self.approval = approval
        self.approval_id = approval.id
        self.task_id = approval.task_id
        self.tool_call_id = approval.tool_call_id
        self.tool_name = approval.tool_name
        super().__init__(
            f"Approval required for ToolCall '{approval.tool_call_id}' "
            f"using Tool '{approval.tool_name}'"
        )


class ProtectedToolExecutionService:
    """Execute safe Tools or signal an unpersisted protected Approval request."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        execution_policy: ToolExecutionPolicy | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._execution_policy = execution_policy or ToolExecutionPolicy()
        self._tool_executor = ToolExecutor(
            tool_registry,
            execution_policy=self._execution_policy,
        )

    def execute(
        self,
        *,
        task_id: UUID,
        tool_call: ToolCall,
    ) -> ToolExecutionResult:
        tool = self._tool_registry.get(tool_call.name)
        metadata = tool.metadata()
        if self._execution_policy.is_automatic_execution_allowed(metadata):
            return self._tool_executor.execute(tool_call)

        approval = Approval(
            task_id=task_id,
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
        )
        raise ApprovalRequired(approval)

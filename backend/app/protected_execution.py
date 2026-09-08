from uuid import UUID

from app.approvals.models import Approval
from app.approvals.repository import ApprovalRepository
from app.llm.schemas import ToolCall
from app.tools.executor import ToolExecutor
from app.tools.policy import ToolExecutionPolicy
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolExecutionResult


class ApprovalRequired(RuntimeError):
    """Signal that a protected ToolCall needs human approval before execution."""

    def __init__(
        self,
        *,
        approval_id: UUID,
        task_id: UUID,
        tool_call_id: str,
        tool_name: str,
    ) -> None:
        self.approval_id = approval_id
        self.task_id = task_id
        self.tool_call_id = tool_call_id
        self.tool_name = tool_name
        super().__init__(
            f"Approval required for ToolCall '{tool_call_id}' "
            f"using Tool '{tool_name}'"
        )


class ProtectedToolExecutionService:
    """Coordinate safe execution and persistent protected ToolCall requests."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        approval_repository: ApprovalRepository,
        execution_policy: ToolExecutionPolicy | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._approval_repository = approval_repository
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
        self._approval_repository.create(approval)
        raise ApprovalRequired(
            approval_id=approval.id,
            task_id=task_id,
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
        )

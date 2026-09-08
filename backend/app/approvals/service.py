from typing import Literal
from uuid import UUID

from app.approvals.models import Approval, ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.tasks.models import TaskStatus
from app.tasks.repository import TaskRepository


class ApprovalNotFoundError(RuntimeError):
    pass


class ApprovalDecisionConflictError(RuntimeError):
    pass


class ApprovalTaskContextError(RuntimeError):
    pass


class ApprovalDecisionService:
    """Decide a pending request without executing or resuming its Task."""

    def __init__(self, approvals: ApprovalRepository, tasks: TaskRepository) -> None:
        self._approvals = approvals
        self._tasks = tasks

    def decide(self, approval_id: UUID, decision: Literal["approve", "reject"]) -> Approval:
        if decision not in ("approve", "reject"):
            raise ValueError("Unknown Approval decision")
        approval = self._approvals.get_by_id(approval_id)
        if approval is None:
            raise ApprovalNotFoundError("Approval not found.")
        if approval.status is not ApprovalStatus.PENDING:
            raise ApprovalDecisionConflictError("Approval is no longer pending.")
        task = self._tasks.get(approval.task_id)
        if task is None or task.status is not TaskStatus.WAITING_APPROVAL:
            raise ApprovalTaskContextError("Approval Task is not waiting for approval.")
        if decision == "approve":
            approval.approve()
        else:
            approval.reject()
        if not self._approvals.save_decision_if_pending(approval):
            raise ApprovalDecisionConflictError("Approval decision was not accepted.")
        return approval

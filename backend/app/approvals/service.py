from collections.abc import Callable
from typing import Literal
from uuid import UUID

from app.approvals.continuation_persistence import ApprovalContinuationPersistence

from app.approvals.models import Approval, ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.tasks.models import TaskStatus
from app.approvals.rejection_persistence import ApprovalRejectionPersistence
from app.tasks.repository import TaskRepository


class ApprovalNotFoundError(RuntimeError):
    pass


class ApprovalDecisionConflictError(RuntimeError):
    pass


class ApprovalTaskContextError(RuntimeError):
    pass


class ApprovalDecisionService:
    """Decide atomically, then dispatch a successful continuation after commit."""

    def __init__(self, approvals: ApprovalRepository, tasks: TaskRepository, rejection: ApprovalRejectionPersistence, continuation: ApprovalContinuationPersistence,
                 resume: Callable[[UUID, UUID], object] | None = None) -> None:
        self._approvals = approvals
        self._tasks = tasks
        self._rejection = rejection
        self._continuation = continuation
        self._resume = resume

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
            task.resume_approved()
            accepted = self._continuation.save(approval, task)
        else:
            approval.reject()
            task.mark_rejected()
            accepted = self._rejection.save(approval, task)
        if not accepted:
            raise ApprovalDecisionConflictError("Approval decision was not accepted.")
        if decision == "approve" and self._resume is not None:
            self._resume(task.id, approval.id)
        return approval

from sqlalchemy.orm import Session

from app.approvals.models import Approval, ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository


class ApprovalContinuationPersistence:
    """Atomically approve and claim continuation; never execute inside this transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, approval: Approval, task: Task) -> bool:
        if approval.status is not ApprovalStatus.APPROVED or task.status is not TaskStatus.RUNNING or approval.task_id != task.id:
            raise ValueError("Continuation requires matching approved/running candidates")
        try:
            # Joins the short transaction begun by decision-context reads.
            if not ApprovalRepository(self._session).stage_decision_if_pending(approval):
                self._session.rollback()
                return False
            if not TaskRepository(self._session).stage_running_if_waiting(task):
                self._session.rollback()
                return False
            self._session.commit()
            self._session.expire_all()
            return True
        except Exception as exc:
            try:
                self._session.rollback()
            except Exception as rollback_error:
                try:
                    self._session.invalidate()
                except Exception:
                    pass
                raise exc from rollback_error
            raise

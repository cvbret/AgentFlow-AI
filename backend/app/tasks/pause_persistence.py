from sqlalchemy.orm import Session

from app.approvals.models import Approval
from app.approvals.repository import ApprovalRepository
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository


class HITLPausePersistence:
    """Commit exactly one Approval and waiting Task in a short transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, task: Task, approval: Approval) -> None:
        if task.status is not TaskStatus.WAITING_APPROVAL or approval.task_id != task.id:
            raise ValueError("Pause requires a waiting Task and its own Approval")
        if self._session.in_transaction():
            raise RuntimeError("Pause requires a Session without an active transaction")
        try:
            self._session.begin()
            ApprovalRepository(self._session).stage_create(approval)
            # Flush the INSERT first; it remains uncommitted if the UPDATE fails.
            self._session.flush()
            TaskRepository(self._session).stage_save(task)
            self._session.flush()
            self._session.commit()
        except Exception as exc:
            try:
                self._session.rollback()
            except Exception as rollback_error:
                # Discard an unusable connection rather than reuse its transaction.
                try:
                    self._session.invalidate()
                except Exception:
                    pass
                raise exc from rollback_error
            raise

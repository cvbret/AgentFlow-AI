from uuid import UUID

from sqlalchemy import update, exists
from sqlalchemy.exc import SQLAlchemyError
from app.db.models.task import TaskRecord
from app.tasks.models import TaskStatus
from sqlalchemy.orm import Session

from app.approvals.exceptions import ApprovalError
from app.approvals.models import Approval, ApprovalStatus
from app.db.models.approval import ApprovalRecord


class ApprovalRepository:
    """Persist and restore Approval entities through an injected Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def stage_create(self, approval: Approval) -> Approval:
        """Add a pending request; the caller owns commit and rollback."""
        if approval.status is not ApprovalStatus.PENDING:
            raise ApprovalError("ApprovalRepository.create requires PENDING Approval")
        if approval.decided_at is not None:
            raise ApprovalError(
                "ApprovalRepository.create requires undecided Approval"
            )
        self._session.add(self._to_record(approval))
        return approval

    def create(self, approval: Approval) -> Approval:
        try:
            self.stage_create(approval)
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return approval

    def stage_decision_if_pending(self, approval: Approval) -> bool:
        """Stage conditional decision; caller owns transaction completion."""
        candidate = Approval.restore(**approval.model_dump())
        if candidate.status not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            raise ApprovalError("Decision persistence requires a terminal Approval")
        result = self._session.execute(
            update(ApprovalRecord)
            .where(
                ApprovalRecord.id == candidate.id,
                ApprovalRecord.task_id == candidate.task_id,
                ApprovalRecord.status == ApprovalStatus.PENDING.value,
                exists().where(
                    TaskRecord.id == ApprovalRecord.task_id,
                    TaskRecord.status == TaskStatus.WAITING_APPROVAL.value,
                ),
            )
            .values(status=candidate.status.value, decided_at=candidate.decided_at)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def save_decision_if_pending(self, approval: Approval) -> bool:
        try:
            accepted = self.stage_decision_if_pending(approval)
            self._session.commit()
            self._session.expire_all()
            return accepted
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def get_by_id(self, approval_id: UUID) -> Approval | None:
        record = self._session.get(ApprovalRecord, approval_id)
        if record is None:
            return None
        return self._to_domain(record)

    def save(self, approval: Approval) -> Approval:
        try:
            record = self._session.get(ApprovalRecord, approval.id)
            if record is None:
                record = self._to_record(approval)
                self._session.add(record)
            else:
                self._update_record(record, approval)
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return approval

    @staticmethod
    def _to_record(approval: Approval) -> ApprovalRecord:
        return ApprovalRecord(
            id=approval.id,
            task_id=approval.task_id,
            tool_call_id=approval.tool_call_id,
            tool_name=approval.tool_name,
            arguments=approval.arguments,
            status=approval.status.value,
            created_at=approval.created_at,
            decided_at=approval.decided_at,
        )

    @staticmethod
    def _update_record(record: ApprovalRecord, approval: Approval) -> None:
        record.task_id = approval.task_id
        record.tool_call_id = approval.tool_call_id
        record.tool_name = approval.tool_name
        record.arguments = approval.arguments
        record.status = approval.status.value
        record.created_at = approval.created_at
        record.decided_at = approval.decided_at

    @staticmethod
    def _to_domain(record: ApprovalRecord) -> Approval:
        try:
            status = ApprovalStatus(record.status)
            return Approval.restore(
                id=record.id,
                task_id=record.task_id,
                tool_call_id=record.tool_call_id,
                tool_name=record.tool_name,
                arguments=record.arguments,
                status=status,
                created_at=record.created_at,
                decided_at=record.decided_at,
            )
        except ApprovalError:
            raise
        except (TypeError, ValueError) as exc:
            raise ApprovalError("Invalid persisted Approval state") from exc

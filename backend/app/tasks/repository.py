from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.task import TaskRecord
from app.tasks.models import Task, TaskError, TaskStatus


class TaskRepository:
    """Persist and restore Task entities through an injected Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def stage_save(self, task: Task) -> Task:
        """Stage a Task write; the caller owns commit and rollback."""
        record = self._session.get(TaskRecord, task.id)
        if record is None:
            record = self._to_record(task)
            self._session.add(record)
        else:
            self._update_record(record, task)
        return self._to_domain(record)

    def save(self, task: Task) -> Task:
        try:
            persisted_task = self.stage_save(task)
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise
        return persisted_task

    def save_failed_if_running(self, task: Task) -> bool:
        """Persist a valid FAILED candidate only while durable state is RUNNING.

        False means no matching RUNNING row, not confirmed pause success.
        """
        candidate = Task.restore(**task.model_dump())
        if candidate.status is not TaskStatus.FAILED:
            raise TaskError("Conditional failure persistence requires a FAILED Task")
        try:
            result = self._session.execute(
                update(TaskRecord)
                .where(
                    TaskRecord.id == candidate.id,
                    TaskRecord.status == TaskStatus.RUNNING.value,
                )
                .values(
                    status=TaskStatus.FAILED.value,
                    result=candidate.result,
                    error=candidate.error,
                    updated_at=candidate.updated_at,
                )
                .execution_options(synchronize_session=False)
            )
            updated = result.rowcount == 1
            self._session.commit()
            self._session.expire_all()
            return updated
        except SQLAlchemyError:
            self._session.rollback()
            raise

    def stage_running_if_waiting(self, task: Task) -> bool:
        candidate = Task.restore(**task.model_dump())
        if candidate.status is not TaskStatus.RUNNING:
            raise TaskError("Continuation claim requires a RUNNING Task")
        result = self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.id == candidate.id, TaskRecord.status == TaskStatus.WAITING_APPROVAL.value)
            .values(status=candidate.status.value, result=None, error=None, updated_at=candidate.updated_at)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def stage_rejected_if_waiting(self, task: Task) -> bool:
        """Conditional rejection write; coordinator owns commit and rollback."""
        candidate = Task.restore(**task.model_dump())
        if candidate.status is not TaskStatus.REJECTED:
            raise TaskError("Rejection persistence requires a REJECTED Task")
        result = self._session.execute(
            update(TaskRecord)
            .where(TaskRecord.id == candidate.id, TaskRecord.status == TaskStatus.WAITING_APPROVAL.value)
            .values(status=candidate.status.value, result=None, error=None, updated_at=candidate.updated_at)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount == 1

    def get(self, task_id: UUID) -> Task | None:
        record = self._session.get(TaskRecord, task_id)
        if record is None:
            return None
        return self._to_domain(record)

    def list(
        self,
        limit: int,
        offset: int,
        status: TaskStatus | None = None,
    ) -> list[Task]:
        query = select(TaskRecord)
        if status is not None:
            query = query.where(TaskRecord.status == status.value)
        query = (
            query.order_by(TaskRecord.created_at.desc(), TaskRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        records = self._session.scalars(query).all()
        return [self._to_domain(record) for record in records]

    @staticmethod
    def _to_record(task: Task) -> TaskRecord:
        return TaskRecord(
            id=task.id,
            status=task.status.value,
            input=task.input,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    @staticmethod
    def _update_record(record: TaskRecord, task: Task) -> None:
        record.status = task.status.value
        record.input = task.input
        record.result = task.result
        record.error = task.error
        record.created_at = task.created_at
        record.updated_at = task.updated_at

    @staticmethod
    def _to_domain(record: TaskRecord) -> Task:
        try:
            status = TaskStatus(record.status)
        except ValueError as exc:
            raise TaskError("Invalid persisted Task state") from exc
        return Task.restore(
            id=record.id,
            status=status,
            input=record.input,
            result=record.result,
            error=record.error,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

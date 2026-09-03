from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models.task import TaskRecord
from app.tasks.models import Task, TaskError, TaskStatus


class TaskRepository:
    """Persist and restore Task entities through an injected Session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, task: Task) -> Task:
        try:
            record = self._session.get(TaskRecord, task.id)
            if record is None:
                record = self._to_record(task)
                self._session.add(record)
            else:
                self._update_record(record, task)

            persisted_task = self._to_domain(record)
            self._session.commit()
        except SQLAlchemyError:
            self._session.rollback()
            raise

        return persisted_task

    def get(self, task_id: UUID) -> Task | None:
        record = self._session.get(TaskRecord, task_id)
        if record is None:
            return None
        return self._to_domain(record)

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

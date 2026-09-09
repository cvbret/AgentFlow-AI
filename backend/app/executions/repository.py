from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.tool_execution import ToolExecutionRecord
from app.executions.exceptions import ExecutionPersistenceConflict, ExecutionPersistenceUncertain
from app.executions.models import ExecutionStatus, ToolExecution


class ExecutionRepository:
    """Each operation owns a short Session/transaction; none span external effects."""
    def __init__(self, session_factory: Callable[[], Session]):
        self._sessions = session_factory

    @contextmanager
    def _transaction(self, *, result_write: bool = False):
        body_completed = False
        try:
            with self._sessions() as session, session.begin():
                yield session
                body_completed = True
        except SQLAlchemyError as exc:
            if body_completed or result_write:
                # A commit exception is not proof of rollback. After a Tool result,
                # even an earlier write failure must not turn its Task into FAILED.
                raise ExecutionPersistenceUncertain("Execution persistence outcome is unconfirmed") from exc
            raise

    @staticmethod
    def _domain(row: ToolExecutionRecord) -> ToolExecution:
        return ToolExecution.restore(**{column.name: getattr(row, column.name)
                                       for column in ToolExecutionRecord.__table__.columns})

    def get(self, task_id: UUID, tool_call_id: str) -> ToolExecution | None:
        with self._sessions() as session:
            row = session.scalar(select(ToolExecutionRecord).where(
                ToolExecutionRecord.task_id == task_id, ToolExecutionRecord.tool_call_id == tool_call_id))
            return None if row is None else self._domain(row)

    def claim(self, candidate: ToolExecution) -> tuple[ToolExecution, bool]:
        candidate = ToolExecution.restore(**candidate.model_dump())
        if candidate.status is not ExecutionStatus.EXECUTING:
            raise ValueError("Claim requires EXECUTING candidate")
        with self._transaction() as session:
            claimed = session.scalar(insert(ToolExecutionRecord).values(**candidate.model_dump())
                .on_conflict_do_nothing(constraint="uq_tool_executions_task_call")
                .returning(ToolExecutionRecord.id))
            row = session.scalar(select(ToolExecutionRecord).where(
                ToolExecutionRecord.task_id == candidate.task_id,
                ToolExecutionRecord.tool_call_id == candidate.tool_call_id))
            result = self._domain(row)
        # Leaving begin() commits before the winner can call a Tool.
        return result, claimed is not None

    def list_for_task(self, task_id: UUID) -> list[ToolExecution]:
        with self._sessions() as session:
            return [self._domain(row) for row in session.scalars(
                select(ToolExecutionRecord).where(ToolExecutionRecord.task_id == task_id))]

    def claim_recovery(self, expected: ToolExecution, *, stale_before: datetime) -> ToolExecution | None:
        if expected.status not in (ExecutionStatus.EXECUTING, ExecutionStatus.UNKNOWN) or expected.updated_at > stale_before:
            return None
        timestamp = max(datetime.now(timezone.utc), expected.updated_at + timedelta(microseconds=1))
        with self._transaction() as session:
            changed = session.execute(update(ToolExecutionRecord).where(
                ToolExecutionRecord.id == expected.id,
                ToolExecutionRecord.status == expected.status.value,
                ToolExecutionRecord.updated_at == expected.updated_at,
                ToolExecutionRecord.updated_at <= stale_before,
            ).values(status=ExecutionStatus.EXECUTING.value, error_code=None, updated_at=timestamp))
            if changed.rowcount != 1:
                return None
        return ToolExecution.restore(**{**expected.model_dump(), "status": ExecutionStatus.EXECUTING,
            "error_code": None, "updated_at": timestamp})

    def finish(self, candidate: ToolExecution, *, expected_updated_at: datetime | None = None) -> None:
        candidate = ToolExecution.restore(**candidate.model_dump())
        if candidate.status is ExecutionStatus.EXECUTING:
            raise ValueError("Finish requires terminal execution")
        with self._transaction(result_write=True) as session:
            changed = session.execute(update(ToolExecutionRecord).where(
                ToolExecutionRecord.id == candidate.id,
                ToolExecutionRecord.status == ExecutionStatus.EXECUTING.value,
                *([ToolExecutionRecord.updated_at == expected_updated_at] if expected_updated_at is not None else []),
            ).values(status=candidate.status.value, result_content=candidate.result_content,
                     error_code=candidate.error_code, updated_at=candidate.updated_at))
            if changed.rowcount != 1:
                raise ExecutionPersistenceConflict("Execution is no longer EXECUTING")

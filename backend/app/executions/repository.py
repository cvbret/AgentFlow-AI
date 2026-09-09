from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models.tool_execution import ToolExecutionRecord
from app.executions.exceptions import ExecutionPersistenceConflict
from app.executions.models import ExecutionStatus, ToolExecution


class ExecutionRepository:
    """Each operation owns a short Session/transaction; none span external effects."""
    def __init__(self, session_factory: Callable[[], Session]):
        self._sessions = session_factory

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
        with self._sessions() as session, session.begin():
            claimed = session.scalar(insert(ToolExecutionRecord).values(**candidate.model_dump())
                .on_conflict_do_nothing(constraint="uq_tool_executions_task_call")
                .returning(ToolExecutionRecord.id))
            row = session.scalar(select(ToolExecutionRecord).where(
                ToolExecutionRecord.task_id == candidate.task_id,
                ToolExecutionRecord.tool_call_id == candidate.tool_call_id))
            result = self._domain(row)
        # Leaving begin() commits before the winner can call a Tool.
        return result, claimed is not None

    def finish(self, candidate: ToolExecution) -> None:
        candidate = ToolExecution.restore(**candidate.model_dump())
        if candidate.status is ExecutionStatus.EXECUTING:
            raise ValueError("Finish requires terminal execution")
        with self._sessions() as session, session.begin():
            changed = session.execute(update(ToolExecutionRecord).where(
                ToolExecutionRecord.id == candidate.id,
                ToolExecutionRecord.status == ExecutionStatus.EXECUTING.value,
            ).values(status=candidate.status.value, result_content=candidate.result_content,
                     error_code=candidate.error_code, updated_at=candidate.updated_at))
            if changed.rowcount != 1:
                raise ExecutionPersistenceConflict("Execution is no longer EXECUTING")

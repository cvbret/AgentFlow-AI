from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import math
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.approvals.models import ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.executions.models import ExecutionStatus, canonical_arguments
from app.executions.repository import ExecutionRepository
from app.llm.schemas import ToolCall
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.resume import TaskResumeService
from app.tasks.service import TaskExecutionService
from app.tasks.pause_persistence import HITLPausePersistence
from app.tools.schemas import IdempotencyMode
from app.tools.exceptions import ToolNotFoundError


class RecoveryOutcome(StrEnum):
    RECOVERED = "recovered"
    NO_ACTION = "no_action"
    STILL_IN_PROGRESS = "still_in_progress"
    RECOVERY_REQUIRED = "recovery_required"
    ORPHAN_CHECKPOINT = "orphan_checkpoint"


class RecoveryResult(BaseModel):
    task_id: UUID
    outcome: RecoveryOutcome


class TaskRecoveryService:
    """Operator-triggered classification and optimistic dispatch; never force replay."""
    def __init__(self, sessions: Callable[[], Session], runtime_provider, *, stale_after_seconds: float,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if not math.isfinite(stale_after_seconds) or stale_after_seconds <= 0:
            raise ValueError("Recovery threshold must be positive and finite")
        self._sessions = sessions
        self._runtime_provider = runtime_provider
        self._executions = ExecutionRepository(sessions)
        self._stale_seconds = stale_after_seconds
        self._clock = clock

    def _persist(self, candidate: Task, expected: Task) -> bool:
        with self._sessions() as session:
            return TaskRepository(session).reconcile_if_unchanged(candidate, expected)

    def _required(self, task: Task, *, orphan=False) -> RecoveryResult:
        if task.status in (TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL):
            candidate = Task.restore(**task.model_dump())
            candidate.require_recovery(now=max(self._clock(), task.updated_at + timedelta(microseconds=1)))
            if not self._persist(candidate, task):
                return RecoveryResult(task_id=task.id, outcome=RecoveryOutcome.STILL_IN_PROGRESS)
        return RecoveryResult(task_id=task.id, outcome=(RecoveryOutcome.ORPHAN_CHECKPOINT if orphan
                                                       else RecoveryOutcome.RECOVERY_REQUIRED))

    def recover(self, task_id: UUID) -> RecoveryResult:
        def result(outcome):
            return RecoveryResult(task_id=task_id, outcome=outcome)
        with self._sessions() as session:
            task = TaskRepository(session).get(task_id)
        runtime = self._runtime_provider()
        evidence = runtime.workflow_evidence(task_id)
        exists = bool(evidence.checkpoint_id)
        if task is None:
            return result(RecoveryOutcome.ORPHAN_CHECKPOINT if exists else RecoveryOutcome.NO_ACTION)
        if task.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.REJECTED):
            healthy_end = (task.status is TaskStatus.SUCCEEDED and exists and not evidence.next_nodes
                and evidence.values.get("task_id") == str(task_id)
                and evidence.values.get("final_answer") == task.result)
            return result(RecoveryOutcome.NO_ACTION if healthy_end or not exists else RecoveryOutcome.ORPHAN_CHECKPOINT)
        if task.status is TaskStatus.PENDING:
            return result(RecoveryOutcome.NO_ACTION if not exists else RecoveryOutcome.ORPHAN_CHECKPOINT)
        cutoff = self._clock() - timedelta(seconds=self._stale_seconds)
        # Do not mistake the live checkpoint-first/business-write interval for an orphan.
        if task.status is TaskStatus.RUNNING and task.updated_at > cutoff:
            return result(RecoveryOutcome.STILL_IN_PROGRESS)
        if not exists or evidence.values.get("task_id") != str(task_id):
            return self._required(task)
        executions = self._executions.list_for_task(task_id)
        pending = evidence.values.get("pending_approval")
        if not evidence.next_nodes:
            if any(row.updated_at > cutoff for row in executions):
                return result(RecoveryOutcome.STILL_IN_PROGRESS)
            answer = evidence.values.get("final_answer")
            if task.status is TaskStatus.RUNNING and isinstance(answer, str) and answer.strip():
                candidate = Task.restore(**task.model_dump())
                candidate.succeed(answer)
                return result(RecoveryOutcome.RECOVERED if self._persist(candidate, task)
                              else RecoveryOutcome.STILL_IN_PROGRESS)
            return self._required(task)
        if evidence.next_nodes not in (("approval_pause",), ("tool",)) or not pending:
            return self._required(task)
        try:
            approval_id = UUID(pending["id"])
            cursor = evidence.values["tool_cursor"]
            if not isinstance(cursor, int) or cursor < 0:
                return self._required(task)
            call = ToolCall.model_validate(evidence.values["tool_calls"][cursor])
            if pending["task_id"] != str(task_id):
                return self._required(task)
        except (ValueError, KeyError, IndexError, TypeError):
            return self._required(task)
        with self._sessions() as session:
            approval = ApprovalRepository(session).get_by_id(approval_id)
        if approval is None:
            return self._required(task, orphan=True)
        if (approval.task_id != task_id or approval.tool_call_id != call.id or approval.tool_name != call.name
                or canonical_arguments(approval.arguments) != canonical_arguments(call.arguments)
                or pending.get("tool_call_id") != call.id or pending.get("tool_name") != call.name
                or canonical_arguments(pending.get("arguments", {})) != canonical_arguments(call.arguments)):
            return self._required(task)
        if (task.status is TaskStatus.WAITING_APPROVAL and approval.status is ApprovalStatus.PENDING
                and evidence.next_nodes == ("approval_pause",)):
            return result(RecoveryOutcome.NO_ACTION)
        if approval.status is not ApprovalStatus.APPROVED:
            return self._required(task, orphan=approval.status is ApprovalStatus.REJECTED)
        if task.status not in (TaskStatus.RUNNING, TaskStatus.RECOVERY_REQUIRED):
            return self._required(task)
        if task.updated_at > cutoff or any(row.updated_at > cutoff for row in executions):
            return result(RecoveryOutcome.STILL_IN_PROGRESS)
        if evidence.next_nodes == ("tool",) and evidence.values.get("resume_approval_id") != str(approval_id):
            return self._required(task)
        execution = next((row for row in executions if row.tool_call_id == call.id), None)
        if execution is not None:
            if (execution.approval_id != approval_id or execution.tool_name != call.name
                    or canonical_arguments(execution.arguments) != canonical_arguments(call.arguments)):
                return self._required(task)
            if execution.status is ExecutionStatus.FAILED:
                return self._required(task)
            if execution.status in (ExecutionStatus.EXECUTING, ExecutionStatus.UNKNOWN):
                try:
                    capability = runtime.recovery_capability(call.name)
                except ToolNotFoundError:
                    return self._required(task)
                if capability not in (IdempotencyMode.EXTERNAL_KEY, IdempotencyMode.INHERENT):
                    return self._required(task)
        claim = Task.restore(**task.model_dump())
        claim.claim_recovery(now=self._clock())
        if not self._persist(claim, task):
            return result(RecoveryOutcome.STILL_IN_PROGRESS)
        if runtime.workflow_evidence(task_id).checkpoint_id != evidence.checkpoint_id:
            return result(RecoveryOutcome.STILL_IN_PROGRESS)
        if execution is not None and execution.status in (ExecutionStatus.EXECUTING, ExecutionStatus.UNKNOWN):
            try:
                runtime.recover_execution(task_id=task_id, approval_id=approval_id,
                                          tool_call=call, stale_before=cutoff)
            except Exception:
                # An uncertain effect or commit leaves durable truth for the next operator request.
                return self._required(claim)
        with self._sessions() as session:
            if evidence.next_nodes == ("approval_pause",):
                TaskResumeService(session, lambda: runtime).resume(task_id, approval_id)
            else:
                service = TaskExecutionService(TaskRepository(session), lambda: runtime, HITLPausePersistence(session))
                service.continue_running(claim, lambda: runtime.resume_pending_tool(task_id=task_id,
                    approval_id=approval_id, checkpoint_id=evidence.checkpoint_id))
        return result(RecoveryOutcome.RECOVERED)

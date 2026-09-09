from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from types import MethodType
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import update, delete, event, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import OperationalError

from test_approval_decision import engine
from test_task_resume import runtime, start, pending, decide, call, snapshot
from app.approvals.models import ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.core.config import Settings
from app.db.models import TaskRecord, ApprovalRecord, ToolExecutionRecord
from app.executions.models import ToolExecution, ExecutionStatus
from app.executions.repository import ExecutionRepository
from app.executions.exceptions import ExecutionPersistenceConflict, ExecutionPersistenceUncertain
from app.llm.schemas import LLMResponse, ChatMessage
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.recovery import TaskRecoveryService, RecoveryOutcome
from app.tools.schemas import IdempotencyMode, ToolExecutionContext, ToolResult
from app.tools.exceptions import ToolExecutionOutcomeUnknown


def age(engine, task_id, *, ledger=True):
    timestamp = datetime.now(timezone.utc) - timedelta(hours=1)
    with engine.begin() as connection:
        connection.execute(update(TaskRecord).where(TaskRecord.id == task_id)
            .values(created_at=timestamp - timedelta(seconds=1), updated_at=timestamp))
        if ledger:
            connection.execute(update(ToolExecutionRecord).where(ToolExecutionRecord.task_id == task_id)
                .values(created_at=timestamp - timedelta(seconds=1), updated_at=timestamp))


def recovery(engine, agent):
    return TaskRecoveryService(lambda: Session(engine), lambda: agent, stale_after_seconds=60)


def prepare(engine, *, approve=True):
    events = []
    agent, llm = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)]), LLMResponse(content="done")])
    task = start(engine, agent)
    approval = pending(engine, task.id)
    if approve:
        with Session(engine) as session:
            decide(session, approval.id)
    return task, approval, agent, llm, events


def loaded(engine, task_id):
    with Session(engine) as session:
        return TaskRepository(session).get(task_id)


def ledger(engine, approval, status):
    repository = ExecutionRepository(lambda: Session(engine))
    row, won = repository.claim(ToolExecution(task_id=approval.task_id, approval_id=approval.id,
        tool_call_id=approval.tool_call_id, tool_name=approval.tool_name, arguments=approval.arguments))
    assert won
    if status is ExecutionStatus.UNKNOWN:
        repository.finish(row.finish(status, error_code="outcome_unknown"))
    return repository.get(approval.task_id, approval.tool_call_id)


def test_stale_approved_dispatch_loss_recovers(engine):
    task, approval, agent, llm, events = prepare(engine)
    age(engine, task.id)
    with patch.object(agent, "resume", wraps=agent.resume) as dispatch:
        assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERED
        dispatch.assert_called_once_with(task_id=task.id, approval_id=approval.id)
    assert loaded(engine, task.id).status is TaskStatus.SUCCEEDED
    assert events == [2] and llm.chat.call_count == 2


@pytest.mark.parametrize("position", ["approval_pause", "tool"])
def test_succeeded_ledger_cached_recovery_count_stays_one(engine, position):
    task, approval, agent, llm, events = prepare(engine)
    if position == "approval_pause":
        agent._approved_execution.execute(task_id=task.id, approval_id=approval.id, tool_call=call(2, True))
    else:
        execute = agent._approved_execution.execute
        def lose_progress(**kwargs):
            execute(**kwargs)
            raise RuntimeError("lost graph progress")
        with patch.object(agent._approved_execution, "execute", side_effect=lose_progress):
            with pytest.raises(RuntimeError, match="lost graph progress"):
                agent.resume(task_id=task.id, approval_id=approval.id)
    assert events == [2]
    assert snapshot(task.id).next == (position,)
    age(engine, task.id)
    fresh, fresh_llm = runtime(engine, events, [LLMResponse(content="recovered")])
    assert recovery(engine, fresh).recover(task.id).outcome is RecoveryOutcome.RECOVERED
    assert events == [2]
    assert loaded(engine, task.id).result == "recovered"
    assert fresh_llm.chat.call_args.kwargs["messages"][-1].content == "3.0"


@pytest.mark.parametrize("status", [ExecutionStatus.EXECUTING, ExecutionStatus.UNKNOWN])
def test_none_capability_requires_operator_attention(engine, status):
    task, approval, agent, llm, events = prepare(engine)
    row = ledger(engine, approval, status)
    age(engine, task.id)
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERY_REQUIRED
    assert loaded(engine, task.id).status is TaskStatus.RECOVERY_REQUIRED
    assert events == [] and llm.chat.call_count == 1
    assert ExecutionRepository(lambda: Session(engine)).get(task.id, approval.tool_call_id).id == row.id


@pytest.mark.parametrize("mode", [IdempotencyMode.EXTERNAL_KEY, IdempotencyMode.INHERENT])
@pytest.mark.parametrize("status", [ExecutionStatus.EXECUTING, ExecutionStatus.UNKNOWN])
def test_capability_recovery_preserves_execution_and_key(engine, mode, status):
    task, approval, agent, llm, events = prepare(engine)
    row = ledger(engine, approval, status)
    tool = agent._tool_registry.get("protected")
    tool.idempotency_mode = mode
    effects, keys, attempts = {}, [], []
    def external(self, data, context):
        keys.append(context.idempotency_key)
        attempts.append(True)
        return ToolResult(content=effects.setdefault(context.idempotency_key, "stable"))
    def inherent(self, data):
        attempts.append(True)
        effects["value"] = data.a  # Explicit inherently idempotent assignment.
        return ToolResult(content="stable")
    tool._execute_with_context = MethodType(external, tool)
    tool._execute = MethodType(inherent, tool)
    if mode is IdempotencyMode.EXTERNAL_KEY:
        tool.execute(approval.arguments, context=ToolExecutionContext(idempotency_key=row.idempotency_key))
    else:
        tool.execute(approval.arguments)
    age(engine, task.id)
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERED
    restored = ExecutionRepository(lambda: Session(engine)).get(task.id, approval.tool_call_id)
    assert restored.status is ExecutionStatus.SUCCEEDED and restored.id == row.id
    assert restored.idempotency_key == row.idempotency_key
    assert len(effects) == 1 and len(attempts) == 2
    if mode is IdempotencyMode.EXTERNAL_KEY:
        assert keys == [row.idempotency_key, row.idempotency_key]
    assert loaded(engine, task.id).status is TaskStatus.SUCCEEDED


def test_recovery_again_ambiguous_stays_unknown_and_requires_attention(engine):
    task, approval, agent, llm, events = prepare(engine)
    ledger(engine, approval, ExecutionStatus.UNKNOWN)
    tool = agent._tool_registry.get("protected")
    tool.idempotency_mode = IdempotencyMode.EXTERNAL_KEY
    attempts = []
    def uncertain(self, data, context):
        attempts.append(context.idempotency_key)
        raise ToolExecutionOutcomeUnknown("still uncertain")
    tool._execute_with_context = MethodType(uncertain, tool)
    age(engine, task.id)
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERY_REQUIRED
    assert loaded(engine, task.id).status is TaskStatus.RECOVERY_REQUIRED
    assert ExecutionRepository(lambda: Session(engine)).get(task.id, approval.tool_call_id).status is ExecutionStatus.UNKNOWN
    recovery(engine, agent).recover(task.id)
    assert len(attempts) == 1 and llm.chat.call_count == 1


def test_completed_graph_reconciles_task_without_execution(engine):
    events = []
    agent, llm = runtime(engine, events, [LLMResponse(content="durable answer")])
    task = Task(input="finish")
    task.start()
    with Session(engine) as session:
        TaskRepository(session).save(task)
    agent.run([ChatMessage(role="user", content=task.input)], task_id=task.id)
    age(engine, task.id)
    with patch.object(agent, "resume") as resume:
        assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERED
        resume.assert_not_called()
    assert loaded(engine, task.id).result == "durable answer"
    assert llm.chat.call_count == 1 and events == []
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.NO_ACTION


def test_healthy_waiting_is_read_only(engine):
    task, approval, agent, llm, events = prepare(engine, approve=False)
    age(engine, task.id)
    before = loaded(engine, task.id).model_dump()
    checkpoint = agent.workflow_evidence(task.id).checkpoint_id
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.NO_ACTION
    assert loaded(engine, task.id).model_dump() == before
    assert agent.workflow_evidence(task.id).checkpoint_id == checkpoint
    assert events == [] and llm.chat.call_count == 1


def test_missing_checkpoint_waiting_requires_recovery(engine):
    from test_approval_decision import seed
    task, _ = seed(engine)
    agent, _ = runtime(engine, [], [])
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERY_REQUIRED
    assert loaded(engine, task.id).status is TaskStatus.RECOVERY_REQUIRED


@pytest.mark.parametrize("orphan", ["task", "approval", "rejected"])
def test_orphan_is_reported_without_deleting_checkpoint(engine, orphan):
    task, approval, agent, llm, events = prepare(engine, approve=False)
    with Session(engine) as session:
        if orphan == "rejected":
            decide(session, approval.id, "reject")
        else:
            session.execute(delete(ApprovalRecord).where(ApprovalRecord.id == approval.id))
            if orphan == "task":
                session.execute(delete(TaskRecord).where(TaskRecord.id == task.id))
            session.commit()
    checkpoint = agent.workflow_evidence(task.id).checkpoint_id
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.ORPHAN_CHECKPOINT
    assert agent.workflow_evidence(task.id).checkpoint_id == checkpoint
    assert events == [] and llm.chat.call_count == 1


@pytest.mark.parametrize("recent", ["task", "execution"])
def test_recent_activity_does_not_dispatch(engine, recent):
    task, approval, agent, llm, events = prepare(engine)
    if recent == "execution":
        ledger(engine, approval, ExecutionStatus.EXECUTING)
        age(engine, task.id, ledger=False)
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.STILL_IN_PROGRESS
    assert loaded(engine, task.id).status is TaskStatus.RUNNING
    assert events == [] and llm.chat.call_count == 1


def test_two_recovery_requests_have_single_dispatch_winner(engine):
    task, approval, agent, llm, events = prepare(engine)
    age(engine, task.id)
    barrier = Barrier(2)
    persist = TaskRepository.reconcile_if_unchanged
    def concurrent(self, candidate, expected):
        if candidate.status is TaskStatus.RUNNING:  # Synchronize claims, not lifecycle completion.
            barrier.wait(timeout=10)
        return persist(self, candidate, expected)
    with patch.object(TaskRepository, "reconcile_if_unchanged", concurrent):
        with patch.object(agent, "resume", wraps=agent.resume) as dispatch:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: recovery(engine, agent).recover(task.id).outcome, range(2)))
            assert dispatch.call_count == 1
    assert sorted(results) == sorted([RecoveryOutcome.RECOVERED, RecoveryOutcome.STILL_IN_PROGRESS])
    assert events == [2]


def test_approval_commit_ack_loss_fresh_recovery_reads_committed_truth(engine):
    task, approval, agent, llm, events = prepare(engine, approve=False)
    with Session(engine) as session:
        commit = session.commit
        def lose_ack():
            commit()
            raise OperationalError("COMMIT", {}, RuntimeError("ack lost"))
        with patch.object(session, "commit", side_effect=lose_ack):
            with pytest.raises(OperationalError):
                decide(session, approval.id)
    assert loaded(engine, task.id).status is TaskStatus.RUNNING
    with Session(engine) as session:
        assert ApprovalRepository(session).get_by_id(approval.id).status is ApprovalStatus.APPROVED
    age(engine, task.id)
    fresh, _ = runtime(engine, events, [LLMResponse(content="after ack loss")])
    assert recovery(engine, fresh).recover(task.id).outcome is RecoveryOutcome.RECOVERED
    assert loaded(engine, task.id).result == "after ack loss" and events == [2]


def test_stale_execution_writer_cannot_overwrite_recovery_claim(engine):
    task, approval, agent, llm, events = prepare(engine)
    ledger(engine, approval, ExecutionStatus.EXECUTING)
    age(engine, task.id)
    repository = ExecutionRepository(lambda: Session(engine))
    old = repository.get(task.id, approval.tool_call_id)
    claimed = repository.claim_recovery(old, stale_before=datetime.now(timezone.utc))
    assert claimed is not None
    with pytest.raises(ExecutionPersistenceConflict):
        repository.finish(old.finish(ExecutionStatus.SUCCEEDED, result_content="stale"), expected_updated_at=old.updated_at)
    repository.finish(claimed.finish(ExecutionStatus.SUCCEEDED, result_content="new"), expected_updated_at=claimed.updated_at)


def test_recovery_required_safe_claim_and_api_filter(engine):
    from app.main import app
    from app.api.dependencies import get_task_recovery_service, get_db_session
    task, approval, agent, llm, events = prepare(engine)
    ledger(engine, approval, ExecutionStatus.UNKNOWN)
    age(engine, task.id)
    service = recovery(engine, agent)
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db_session] = sessions
    app.dependency_overrides[get_task_recovery_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.post(f"/api/tasks/{task.id}/recover")
            assert response.json() == {"task_id": str(task.id), "outcome": "recovery_required"}
            assert client.get(f"/api/tasks/{task.id}").json()["status"] == "recovery_required"
            assert client.get("/api/tasks?status=recovery_required").json()["items"][0]["id"] == str(task.id)
            agent._tool_registry.get("protected").idempotency_mode = IdempotencyMode.INHERENT
            age(engine, task.id)
            assert client.post(f"/api/tasks/{task.id}/recover").json()["outcome"] == "recovered"
            assert client.get(f"/api/tasks/{task.id}").json()["status"] == "succeeded"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_recovery_threshold_must_be_positive_finite(value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_api_key="test", llm_base_url="https://example.com", llm_model="test", recovery_stale_after_seconds=value)
    with pytest.raises(ValueError):
        TaskRecoveryService(lambda: None, lambda: None, stale_after_seconds=value)



def test_normal_unknown_enters_recovery_required_then_safe_recovery(engine):
    task, approval, agent, llm, events = prepare(engine)
    tool = agent._tool_registry.get("protected")
    tool.idempotency_mode = IdempotencyMode.EXTERNAL_KEY
    keys, effects = [], {}
    def endpoint(self, data, context):
        keys.append(context.idempotency_key)
        effects[context.idempotency_key] = "confirmed"
        if len(keys) == 1:
            raise ToolExecutionOutcomeUnknown("lost acknowledgement")
        return ToolResult(content=effects[context.idempotency_key])
    tool._execute_with_context = MethodType(endpoint, tool)
    from app.tasks.resume import TaskResumeService
    with Session(engine) as session:
        with pytest.raises(ToolExecutionOutcomeUnknown):
            TaskResumeService(session, lambda: agent).resume(task.id, approval.id)
    assert loaded(engine, task.id).status is TaskStatus.RECOVERY_REQUIRED
    age(engine, task.id)
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERED
    assert len(keys) == 2 and keys[0] == keys[1] and len(effects) == 1
    assert loaded(engine, task.id).status is TaskStatus.SUCCEEDED


def test_completed_reconciliation_cannot_overwrite_changed_task(engine):
    agent, llm = runtime(engine, [], [LLMResponse(content="final")])
    task = Task(input="conditional completion")
    task.start()
    with Session(engine) as session:
        TaskRepository(session).save(task)
    agent.run([ChatMessage(role="user", content=task.input)], task_id=task.id)
    age(engine, task.id)
    persist = TaskRepository.reconcile_if_unchanged
    def change_before_write(self, candidate, expected):
        with Session(engine) as session:
            current = TaskRepository(session).get(task.id)
            current.fail("newer failure")
            TaskRepository(session).save(current)
        return persist(self, candidate, expected)
    with patch.object(TaskRepository, "reconcile_if_unchanged", change_before_write):
        assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.STILL_IN_PROGRESS
    assert loaded(engine, task.id).status is TaskStatus.FAILED
    assert loaded(engine, task.id).error == "newer failure"
    assert llm.chat.call_count == 1


@pytest.mark.parametrize("mismatch", ["arguments", "approval_status", "checkpoint_task"])
def test_recovery_revalidates_identity_and_authorization(engine, mismatch):
    task, approval, agent, llm, events = prepare(engine)
    ledger(engine, approval, ExecutionStatus.UNKNOWN)
    agent._tool_registry.get("protected").idempotency_mode = IdempotencyMode.INHERENT
    age(engine, task.id)
    if mismatch == "checkpoint_task":
        evidence = agent.workflow_evidence(task.id)
        from app.workflows.recovery import WorkflowEvidence
        changed = WorkflowEvidence(evidence.checkpoint_id, evidence.next_nodes,
                                   {**evidence.values, "task_id": str(uuid4())})
        with patch.object(agent, "workflow_evidence", return_value=changed):
            outcome = recovery(engine, agent).recover(task.id).outcome
    else:
        with Session(engine) as session:
            row = session.get(ApprovalRecord, approval.id)
            if mismatch == "arguments":
                row.arguments = {"operation": "add", "a": 999, "b": 1}
            else:
                row.status, row.decided_at = "PENDING", None
            session.commit()
        outcome = recovery(engine, agent).recover(task.id).outcome
    assert outcome is RecoveryOutcome.RECOVERY_REQUIRED
    assert events == [] and llm.chat.call_count == 1



def test_recovery_can_pause_for_second_approval(engine):
    events = []
    agent, llm = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True), call(3, True)]), LLMResponse(content="done")])
    task = start(engine, agent)
    first = pending(engine, task.id)
    with Session(engine) as session:
        decide(session, first.id)
    age(engine, task.id)
    assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERED
    second = pending(engine, task.id)
    assert first.id != second.id and loaded(engine, task.id).status is TaskStatus.WAITING_APPROVAL
    assert events == [2] and llm.chat.call_count == 1
    with Session(engine) as session:
        decide(session, second.id, runtime=agent)
    assert events == [2, 3] and loaded(engine, task.id).status is TaskStatus.SUCCEEDED


def test_removed_tool_capability_requires_recovery(engine):
    from app.tools.exceptions import ToolNotFoundError
    task, approval, agent, llm, events = prepare(engine)
    ledger(engine, approval, ExecutionStatus.UNKNOWN)
    age(engine, task.id)
    with patch.object(agent, "recovery_capability", side_effect=ToolNotFoundError("removed")):
        assert recovery(engine, agent).recover(task.id).outcome is RecoveryOutcome.RECOVERY_REQUIRED
    assert loaded(engine, task.id).status is TaskStatus.RECOVERY_REQUIRED and events == []


@pytest.mark.parametrize("exit_status", [TaskStatus.FAILED, TaskStatus.SUCCEEDED, TaskStatus.WAITING_APPROVAL])
def test_old_continuation_cannot_write_any_lifecycle_exit(engine, exit_status):
    from app.agents.runtime import AgentResult
    from app.approvals.models import Approval
    from app.llm.client import LLMProviderError
    from app.protected_execution import ApprovalRequired
    from app.tasks.pause_persistence import HITLPausePersistence
    from app.tasks.repository import TaskOwnershipLost
    from app.tasks.service import TaskExecutionService

    old = Task(input="generation fence")
    old.start()
    with Session(engine) as session:
        TaskRepository(session).save(old)
    newer = Task.restore(**old.model_dump())
    newer.claim_recovery()
    approval = Approval(task_id=old.id, tool_call_id="late_pause", tool_name="protected", arguments={})

    def invoke():
        # Simulate the independent recovery owner committing while A is executing.
        with Session(engine) as session:
            assert TaskRepository(session).reconcile_if_unchanged(newer, old)
        if exit_status is TaskStatus.FAILED:
            raise LLMProviderError("old executor failed")
        if exit_status is TaskStatus.WAITING_APPROVAL:
            raise ApprovalRequired(approval)
        return AgentResult(content="old executor succeeded")

    with Session(engine) as session:
        repository = TaskRepository(session)
        with patch.object(repository, "save_failed_if_running", wraps=repository.save_failed_if_running) as failed:
            with pytest.raises(LLMProviderError if exit_status is TaskStatus.FAILED else TaskOwnershipLost):
                TaskExecutionService(repository, lambda: None, HITLPausePersistence(session)).continue_running(old, invoke)
            if exit_status is TaskStatus.FAILED:
                failed.assert_called_once()
            else:
                failed.assert_not_called()  # No generic FAILED fallback after a lost CAS.
    assert loaded(engine, old.id).model_dump() == newer.model_dump()
    with Session(engine) as session:
        assert session.scalar(select(ApprovalRecord.id).where(ApprovalRecord.task_id == old.id)) is None


def test_late_executor_cannot_fail_new_recovery_owner(engine):
    from app.tasks.resume import TaskResumeService

    task, approval, actor_a, _, events = prepare(engine)
    actor_b, b_llm = runtime(engine, events, [LLMResponse(content="B completed")])
    a_entered, b_entered, a_done = Event(), Event(), Event()
    effects, keys, failure_writes, claims = {}, [], [], []
    executions = ExecutionRepository(lambda: Session(engine))
    original_fail = TaskRepository.save_failed_if_running
    tool_a = actor_a._tool_registry.get("protected")
    tool_b = actor_b._tool_registry.get("protected")
    tool_a.idempotency_mode = tool_b.idempotency_mode = IdempotencyMode.EXTERNAL_KEY

    def external(context):
        keys.append(context.idempotency_key)
        return ToolResult(content=effects.setdefault(context.idempotency_key, "3.0"))

    def execute_a(arguments, *, context):
        result = external(context)
        claims.append((loaded(engine, task.id), executions.get(task.id, approval.tool_call_id)))
        a_entered.set()
        assert b_entered.wait(15), "Recovery B did not claim execution"
        return result  # Its subsequent ledger finish and Task FAILED write must both lose.

    def execute_b(arguments, *, context):
        claims.append((loaded(engine, task.id), executions.get(task.id, approval.tool_call_id)))
        b_entered.set()
        assert a_done.wait(15), "Old actor A did not stop"
        assert failure_writes == [False]
        assert loaded(engine, task.id).model_dump() == claims[1][0].model_dump()
        return external(context)

    def record_failure(repository, candidate, expected):
        accepted = original_fail(repository, candidate, expected)
        failure_writes.append(accepted)
        return accepted

    def run_a():
        try:
            with Session(engine) as session:
                with pytest.raises(ExecutionPersistenceConflict):
                    TaskResumeService(session, lambda: actor_a).resume(task.id, approval.id)
        finally:
            a_done.set()

    # Advance the logical inactivity clock without mutating either actor's captured
    # database generation. No real-time sleep and no lease/liveness assumptions.
    later = datetime.now(timezone.utc) + timedelta(hours=1)
    with patch("app.tasks.models.utc_now", return_value=later), \
         patch.object(tool_a, "execute", side_effect=execute_a), \
         patch.object(tool_b, "execute", side_effect=execute_b), \
         patch.object(TaskRepository, "save_failed_if_running", new=record_failure):
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(run_a)
            assert a_entered.wait(15)
            result = TaskRecoveryService(lambda: Session(engine), lambda: actor_b,
                stale_after_seconds=60, clock=lambda: later).recover(task.id)
            future.result(timeout=15)
    assert result.outcome is RecoveryOutcome.RECOVERED
    assert len(claims) == 2
    assert claims[1][0].updated_at > claims[0][0].updated_at
    assert claims[1][1].updated_at > claims[0][1].updated_at
    assert claims[1][1].id == claims[0][1].id
    assert failure_writes == [False]
    assert len(keys) == 2 and keys[0] == keys[1] and len(effects) == 1
    assert loaded(engine, task.id).status is TaskStatus.SUCCEEDED
    assert loaded(engine, task.id).result == "B completed"
    assert executions.get(task.id, approval.tool_call_id).status is ExecutionStatus.SUCCEEDED
    assert b_llm.chat.call_count == 1


def test_task_resume_result_commit_ack_loss_recovers_from_cached_success(engine):
    from app.tasks.resume import TaskResumeService

    task, approval, actor_a, _, events = prepare(engine)
    before = loaded(engine, task.id)
    commits = []
    error = OperationalError("COMMIT", {}, RuntimeError("result acknowledgement lost"))

    def sessions():
        session = Session(engine)
        def after_commit(current):
            commits.append(True)
            if len(commits) == 2:  # Claim committed, then SUCCEEDED really committed.
                raise error
        event.listen(session, "after_commit", after_commit)
        return session

    actor_a._approved_execution._executions = ExecutionRepository(sessions)
    with Session(engine) as session:
        with pytest.raises(ExecutionPersistenceUncertain) as raised:
            TaskResumeService(session, lambda: actor_a).resume(task.id, approval.id)
    assert raised.value.__cause__ is error
    assert len(commits) == 2 and events == [2]
    assert loaded(engine, task.id).model_dump() == before.model_dump()
    assert before.status is TaskStatus.RUNNING
    executions = ExecutionRepository(lambda: Session(engine))
    stored = executions.get(task.id, approval.tool_call_id)
    assert stored.status is ExecutionStatus.SUCCEEDED
    assert snapshot(task.id).next == ("tool",)
    with Session(engine) as session:
        assert ApprovalRepository(session).get_by_id(approval.id).status is ApprovalStatus.APPROVED
    actor_a.close()
    age(engine, task.id)
    fresh, llm = runtime(engine, events, [LLMResponse(content="cached recovery completed")])
    assert recovery(engine, fresh).recover(task.id).outcome is RecoveryOutcome.RECOVERED
    assert events == [2]  # Complete application path: one call before AND after recovery.
    assert loaded(engine, task.id).status is TaskStatus.SUCCEEDED
    assert loaded(engine, task.id).result == "cached recovery completed"
    assert executions.get(task.id, approval.tool_call_id).status is ExecutionStatus.SUCCEEDED
    assert snapshot(task.id).next == ()
    assert llm.chat.call_count == 1
    assert llm.chat.call_args.kwargs["messages"][-1].content == stored.result_content


def test_known_no_effect_tool_failure_still_fails_task_and_ledger(engine):
    from app.tasks.resume import TaskResumeService
    from app.tools.exceptions import ToolExecutionFailedWithoutEffect

    task, approval, agent, _, events = prepare(engine)
    error = ToolExecutionFailedWithoutEffect("known rejection before effect")
    tool = agent._tool_registry.get("protected")
    with patch.object(tool, "execute", side_effect=error):
        with Session(engine) as session:
            with pytest.raises(ToolExecutionFailedWithoutEffect) as raised:
                TaskResumeService(session, lambda: agent).resume(task.id, approval.id)
    assert raised.value is error
    assert events == []
    stored_task = loaded(engine, task.id)
    assert stored_task.status is TaskStatus.FAILED
    assert stored_task.error == "Agent execution failed."
    stored = ExecutionRepository(lambda: Session(engine)).get(task.id, approval.tool_call_id)
    assert stored.status is ExecutionStatus.FAILED and stored.error_code == "known_no_effect"

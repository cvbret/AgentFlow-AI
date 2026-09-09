"""TASK-028: real PostgreSQL Agent continuation, not crash-safe exactly-once."""
import gc
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from test_approval_decision import engine
from app.agents.runtime import AgentRuntime, AgentMaxStepsExceededError
from app.approved_execution import ApprovedToolExecutionService, ResumeAuthorizationError
from app.approvals.models import Approval, ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.approvals.service import ApprovalDecisionService, ApprovalDecisionConflictError
from app.approvals.continuation_persistence import ApprovalContinuationPersistence
from app.approvals.rejection_persistence import ApprovalRejectionPersistence
from app.db.models import ApprovalRecord
from app.llm.schemas import ChatMessage, LLMResponse, ToolCall
from app.protected_execution import ApprovalRequired, ProtectedToolExecutionService
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.pause_persistence import HITLPausePersistence
from app.tasks.resume import TaskResumeService
from app.tasks.service import TaskExecutionService
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry
from app.tools.exceptions import ToolInputValidationError, ToolExecutionError
from app.workflows.agent import build_agent_graph
from app.workflows.checkpoint import open_checkpointer


def registry(events):
    class Safe(CalculatorTool):
        name = "safe"
        def _execute(self, data):
            events.append(int(data.a))
            return super()._execute(data)
    class Protected(Safe):
        name = "protected"
        side_effect_free = False
    result = ToolRegistry()
    result.register(Safe())
    result.register(Protected())
    return result


def call(position, protected=False, **arguments):
    return ToolCall(id=f"call_{position}", name="protected" if protected else "safe",
                    arguments=arguments or {"operation": "add", "a": position, "b": 1})


def runtime(engine, events, responses, *, max_steps=5):
    llm = Mock()
    llm.chat.side_effect = responses
    def load(approval_id):
        with Session(engine) as session:
            return ApprovalRepository(session).get_by_id(approval_id)
    return AgentRuntime(llm, registry(events), max_steps=max_steps,
        checkpointer_factory=lambda: open_checkpointer(os.environ["DATABASE_URL"]),
        approval_loader=load), llm


def start(engine, runtime):
    with Session(engine) as session:
        return TaskExecutionService(TaskRepository(session), lambda: runtime,
                                    HITLPausePersistence(session)).execute("calculate")


def pending(engine, task_id):
    with Session(engine) as session:
        identity = session.scalars(select(ApprovalRecord.id).where(
            ApprovalRecord.task_id == task_id, ApprovalRecord.status == "PENDING")).one()
        return ApprovalRepository(session).get_by_id(identity)


def decide(session, approval_id, decision="approve", runtime=None, callback=None):
    return ApprovalDecisionService(ApprovalRepository(session), TaskRepository(session),
        ApprovalRejectionPersistence(session), ApprovalContinuationPersistence(session),
        resume=callback or (TaskResumeService(session, lambda: runtime).resume if runtime else None)
    ).decide(approval_id, decision)


def snapshot(task_id):
    # A new saver/graph, with unusable execution dependencies: reads only durable data.
    with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
        graph = build_agent_graph(Mock(), [], Mock(), max_steps=5, checkpointer=saver)
        return graph.get_state({"configurable": {"thread_id": str(task_id)}})


@pytest.mark.parametrize("multi", [False, True])
def test_fresh_runtime_durable_resume_and_cursor(engine, multi):
    events = []
    calls = [call(1), call(2, True), call(3)] if multi else [call(2, True)]
    runtime_a, llm_a = runtime(engine, events, [LLMResponse(tool_calls=calls)])
    task = start(engine, runtime_a)
    approval = pending(engine, task.id)
    assert task.status is TaskStatus.WAITING_APPROVAL
    assert events == ([1] if multi else [])
    durable = snapshot(task.id)
    assert durable.next == ("approval_pause",)
    assert durable.values["tool_cursor"] == (1 if multi else 0)
    assert durable.values["pending_approval"]["id"] == str(approval.id)
    assert durable.values["step_count"] == 1
    runtime_a.close()
    llm_a.close.assert_called_once()
    del runtime_a, durable
    gc.collect()

    runtime_b, llm_b = runtime(engine, events, [LLMResponse(content="done")])
    commits = []
    with Session(engine) as session:
        def before_commit(current):
            commits.append(True)
            with Session(engine) as observer:
                assert TaskRepository(observer).get(task.id).status is TaskStatus.WAITING_APPROVAL
                assert ApprovalRepository(observer).get_by_id(approval.id).status is ApprovalStatus.PENDING
            assert current.execute(text("SELECT status FROM tasks WHERE id=:id"), {"id": task.id}).scalar_one() == "RUNNING"
            assert current.execute(text("SELECT status FROM approvals WHERE id=:id"), {"id": approval.id}).scalar_one() == "APPROVED"
        event.listen(session, "before_commit", before_commit)
        decide(session, approval.id)
        event.remove(session, "before_commit", before_commit)
        assert len(commits) == 1 and not session.in_transaction()
    with Session(engine) as session:
        result = TaskResumeService(session, lambda: runtime_b).resume(task.id, approval.id)
    assert result.status is TaskStatus.SUCCEEDED and result.result == "done"
    assert events == ([1, 2, 3] if multi else [2])
    history = llm_b.chat.call_args.kwargs["messages"]
    assert [m.tool_call_id for m in history if m.role == "tool"] == [c.id for c in calls]
    llm_b.chat.assert_called_once()
    assert snapshot(task.id).next == ()
    with Session(engine) as session:
        assert ApprovalRepository(session).get_by_id(approval.id).status is ApprovalStatus.APPROVED
        assert TaskRepository(session).get(task.id).status is TaskStatus.SUCCEEDED
    runtime_b.close()


def test_second_protected_call_creates_distinct_pause(engine):
    events = []
    first, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(1), call(2, True), call(3, True)])])
    task = start(engine, first)
    approval_a = pending(engine, task.id)
    first.close()
    second, llm = runtime(engine, events, [LLMResponse(content="complete")])
    with Session(engine) as session:
        decide(session, approval_a.id, runtime=second)
    approval_b = pending(engine, task.id)
    assert approval_a.id != approval_b.id
    assert events == [1, 2]
    llm.chat.assert_not_called()
    with Session(engine) as session:
        assert TaskRepository(session).get(task.id).status is TaskStatus.WAITING_APPROVAL
        decide(session, approval_b.id, runtime=second)
    assert events == [1, 2, 3]
    with Session(engine) as session:
        assert TaskRepository(session).get(task.id).status is TaskStatus.SUCCEEDED


@pytest.mark.parametrize("fault", ["wrong_task", "wrong_approval", "missing", "pending", "rejected", "arguments", "tool_call_id", "tool_name"])
def test_resume_authorization_fails_closed(engine, fault):
    events = []
    agent, llm = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)])])
    task = start(engine, agent)
    approval = pending(engine, task.id)
    with Session(engine) as session:
        if fault not in ("pending", "rejected"):
            decide(session, approval.id)
        elif fault == "rejected":
            decide(session, approval.id, "reject")
        if fault in ("missing", "arguments", "tool_call_id", "tool_name"):
            row = session.get(ApprovalRecord, approval.id)
            if fault == "missing":
                session.delete(row)
            elif fault == "arguments":
                row.arguments = {"operation": "add", "a": True, "b": 1}
            else:
                setattr(row, fault, "different")
            session.commit()
    with pytest.raises(ResumeAuthorizationError):
        agent.resume(task_id=uuid4() if fault == "wrong_task" else task.id,
                     approval_id=uuid4() if fault == "wrong_approval" else approval.id)
    assert events == [] and llm.chat.call_count == 1


def test_checkpoint_exists_before_business_pause_failure(engine):
    events = []
    agent, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)])])
    captured = []
    def fail(task, approval):
        captured.append(task.id)
        state = snapshot(task.id)
        assert state.next == ("approval_pause",)
        assert state.values["pending_approval"]["id"] == str(approval.id)
        raise RuntimeError("business pause failed")
    with patch.object(HITLPausePersistence, "save", side_effect=fail):
        with pytest.raises(RuntimeError, match="business pause failed"):
            start(engine, agent)
    assert events == []
    with Session(engine) as session:
        assert TaskRepository(session).get(captured[0]).status is TaskStatus.FAILED
        assert session.scalars(select(ApprovalRecord).where(ApprovalRecord.task_id == captured[0])).all() == []
    assert snapshot(captured[0]).next == ("approval_pause",)  # orphan deliberately retained


def test_checkpoint_failure_never_exposes_business_pause(engine):
    events = []
    agent, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)])])
    from langgraph.checkpoint.postgres import PostgresSaver
    with patch.object(PostgresSaver, "put", side_effect=RuntimeError("checkpoint failed")):
        with patch.object(HITLPausePersistence, "save") as pause:
            with pytest.raises(RuntimeError, match="checkpoint failed"):
                start(engine, agent)
            pause.assert_not_called()
    assert events == []


@pytest.mark.parametrize("failure", ["llm", "budget", "input", "tool"])
def test_resume_failure_uses_existing_failed_contract(engine, failure):
    events = []
    args = {"operation": "invalid", "a": 2, "b": 1} if failure == "input" else (
        {"operation": "divide", "a": 2, "b": 0} if failure == "tool" else {})
    agent, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True, **args)])],
                       max_steps=1 if failure == "budget" else 5)
    task = start(engine, agent)
    approval = pending(engine, task.id)
    fresh, _ = runtime(engine, events, [RuntimeError("private failure")])
    expected = {"llm": RuntimeError, "budget": AgentMaxStepsExceededError,
                "input": ToolInputValidationError, "tool": ToolExecutionError}[failure]
    with Session(engine) as session:
        decide(session, approval.id)
        with pytest.raises(expected):
            TaskResumeService(session, lambda: fresh).resume(task.id, approval.id)
    with Session(engine) as session:
        task = TaskRepository(session).get(task.id)
        assert task.status is TaskStatus.FAILED
        assert "private" not in task.error
        assert ApprovalRepository(session).get_by_id(approval.id).status is ApprovalStatus.APPROVED


@pytest.mark.parametrize("decisions", [("approve", "approve"), ("approve", "reject")])
def test_postgres_single_winner_dispatches_at_most_one_resume(engine, decisions):
    events = []
    agent, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)])])
    task = start(engine, agent)
    approval = pending(engine, task.id)
    barrier = Barrier(2)
    resumes = []
    class ConcurrentTasks(TaskRepository):
        def get(self, task_id):
            task = super().get(task_id)
            barrier.wait(timeout=10)
            return task
    def request(decision):
        fresh, _ = runtime(engine, events, [LLMResponse(content="done")])
        with Session(engine) as session:
            def resume(task_id, approval_id):
                assert not session.in_transaction()
                resumes.append(approval_id)
                return TaskResumeService(session, lambda: fresh).resume(task_id, approval_id)
            service = ApprovalDecisionService(ApprovalRepository(session), ConcurrentTasks(session),
                ApprovalRejectionPersistence(session), ApprovalContinuationPersistence(session), resume)
            try:
                service.decide(approval.id, decision)
                return decision
            except ApprovalDecisionConflictError:
                return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request, decisions))
    assert results.count("conflict") == 1
    winner = next(r for r in results if r != "conflict")
    assert len(resumes) == (1 if winner == "approve" else 0)
    assert events == ([2] if winner == "approve" else [])
    with Session(engine) as session:
        assert TaskRepository(session).get(task.id).status is (TaskStatus.SUCCEEDED if winner == "approve" else TaskStatus.REJECTED)


@pytest.mark.parametrize("failure", ["task", "commit"])
def test_claim_failure_rolls_back_both_without_resume(engine, failure):
    events = []
    agent, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)])])
    task = start(engine, agent)
    approval = pending(engine, task.id)
    with engine.begin() as conn:
        conn.execute(text("CREATE FUNCTION task028_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'claim failure'; END; $$"))
        ddl = ("CREATE CONSTRAINT TRIGGER task028_failure AFTER UPDATE ON tasks DEFERRABLE INITIALLY DEFERRED "
               if failure == "commit" else "CREATE TRIGGER task028_failure BEFORE UPDATE ON tasks ")
        conn.execute(text(ddl + "FOR EACH ROW EXECUTE FUNCTION task028_fail()"))
    try:
        resume = Mock()
        with Session(engine) as session:
            with pytest.raises(SQLAlchemyError, match="claim failure"):
                decide(session, approval.id, callback=resume)
            assert not session.in_transaction()
        resume.assert_not_called()
        assert events == []
        with Session(engine) as session:
            assert TaskRepository(session).get(task.id).status is TaskStatus.WAITING_APPROVAL
            assert ApprovalRepository(session).get_by_id(approval.id).status is ApprovalStatus.PENDING
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TRIGGER task028_failure ON tasks"))
            conn.execute(text("DROP FUNCTION task028_fail()"))


def test_domain_resume_requires_waiting():
    task = Task(input="resume")
    with pytest.raises(Exception, match="Cannot transition"):
        task.resume_approved()
    task.start()
    task.mark_waiting_approval()
    before = task.updated_at
    task.resume_approved()
    assert task.status is TaskStatus.RUNNING and task.updated_at >= before
    with pytest.raises(Exception, match="Cannot transition"):
        task.resume_approved()


def test_real_api_approve_dispatches_fresh_runtime_and_keeps_dto(engine):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.api.dependencies import get_agent_runtime_provider, get_db_session
    events = []
    active, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(1), call(2, True), call(3)])])
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db_session] = sessions
    app.dependency_overrides[get_agent_runtime_provider] = lambda: lambda: active
    try:
        with TestClient(app) as client:
            response = client.post("/api/agent/run", json={"message": "calculate"})
            assert response.status_code == 200
            task_id = UUID(response.json()["task_id"])
            approval = pending(engine, task_id)
            assert events == [1]
            active.close()
            active, llm = runtime(engine, events, [LLMResponse(content="finished")])
            response = client.post(f"/api/approvals/{approval.id}/approve")
            assert response.status_code == 200
            assert set(response.json()) == {"approval_id", "task_id", "status", "decided_at"}
            assert response.json()["status"] == "approved"
            assert client.get(f"/api/tasks/{task_id}").json()["status"] == "succeeded"
            assert events == [1, 2, 3]
            assert client.post(f"/api/approvals/{approval.id}/approve").status_code == 409
            assert events == [1, 2, 3]
            llm.chat.assert_called_once()
    finally:
        active.close()
        app.dependency_overrides.clear()


@pytest.mark.parametrize("payload", [{"approved": True}, "matching_but_unapproved"])
def test_raw_resume_payload_cannot_authorize_tool(engine, payload):
    from langgraph.types import Command
    events = []
    agent, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)])])
    task = start(engine, agent)
    approval = pending(engine, task.id)
    def load(identity):
        with Session(engine) as session:
            return ApprovalRepository(session).get_by_id(identity)
    tools = registry(events)
    with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
        graph = build_agent_graph(Mock(), tools.list(), ProtectedToolExecutionService(tools),
            max_steps=5, checkpointer=saver, approved_execution=ApprovedToolExecutionService(tools, load))
        if isinstance(payload, str):
            payload = {"task_id": str(task.id), "approval_id": str(approval.id)}
        with pytest.raises(ResumeAuthorizationError):
            graph.invoke(Command(resume=payload), {"configurable": {"thread_id": str(task.id)}})
    assert events == []

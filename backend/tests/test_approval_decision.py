import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db_session, get_agent_runtime_provider
from app.agents.runtime import AgentResult
from app.approvals.models import Approval, ApprovalStatus
from app.approvals.exceptions import ApprovalError
from app.approvals.continuation_persistence import ApprovalContinuationPersistence
from app.approvals.repository import ApprovalRepository
from app.approvals.rejection_persistence import ApprovalRejectionPersistence
from app.approvals.service import ApprovalDecisionService, ApprovalDecisionConflictError, ApprovalTaskContextError
from app.db.models import ApprovalRecord, TaskRecord, ToolExecutionRecord
from app.main import app
from app.tasks import Task, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.pause_persistence import HITLPausePersistence
from app.tools.base import Tool
from app.agents.runtime import AgentRuntime


@pytest.fixture
def engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(delete(ToolExecutionRecord))
            connection.execute(delete(ApprovalRecord))
            connection.execute(delete(TaskRecord))
        engine.dispose()


def seed(engine):
    task = Task(input="decision")
    task.start()
    approval = Approval(task_id=task.id, tool_call_id="call_decision", tool_name="protected", arguments={"nested": [1, {"key": "value"}]})
    with Session(engine) as session:
        TaskRepository(session).save(task)
        expected = Task.restore(**task.model_dump())
        task.mark_waiting_approval()
        HITLPausePersistence(session).save(task, approval, expected=expected)
    return task, approval


@pytest.fixture
def client(engine):
    def session():
        with Session(engine) as current:
            yield current
    app.dependency_overrides[get_db_session] = session
    runtime = Mock(spec=AgentRuntime)
    runtime.resume.return_value = AgentResult(content="continued")
    app.dependency_overrides[get_agent_runtime_provider] = lambda: lambda: runtime
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_api_decision_and_all_terminal_conflicts(engine, client, decision):
    task, approval = seed(engine)
    with patch.object(Tool, "execute") as execute, patch.object(AgentRuntime, "run") as run:
        response = client.post(f"/api/approvals/{approval.id}/{decision}")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"approval_id", "task_id", "status", "decided_at"}
        assert body["approval_id"] == str(approval.id)
        assert body["task_id"] == str(task.id)
        assert body["status"] == ("approved" if decision == "approve" else "rejected")
        for repeat in ("approve", "reject"):
            assert client.post(f"/api/approvals/{approval.id}/{repeat}").status_code == 409
        execute.assert_not_called()
        run.assert_not_called()
    with Session(engine) as observer:
        loaded = ApprovalRepository(observer).get_by_id(approval.id)
        assert loaded.decided_at is not None
        assert loaded.decided_at >= loaded.created_at
        assert loaded.decided_at.isoformat().replace("+00:00", "Z") == body["decided_at"]
        for field in ("id", "task_id", "tool_call_id", "tool_name", "arguments", "created_at"):
            assert getattr(loaded, field) == getattr(approval, field)
        loaded_task = TaskRepository(observer).get(task.id)
        assert loaded_task.status is (TaskStatus.SUCCEEDED if decision == "approve" else TaskStatus.REJECTED)
        assert loaded_task.result == ("continued" if decision == "approve" else None)
        assert loaded_task.error is None


def test_api_unknown_and_invalid_id(client):
    assert client.post(f"/api/approvals/{uuid4()}/approve").status_code == 404
    assert client.post("/api/approvals/invalid/reject").status_code == 422


@pytest.mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.SUCCEEDED, TaskStatus.FAILED])
def test_nonwaiting_context_rejected(engine, client, status):
    task = Task(input="invalid context")
    if status is not TaskStatus.PENDING:
        task.start()
    if status is TaskStatus.SUCCEEDED:
        task.succeed("done")
    if status is TaskStatus.FAILED:
        task.fail("failure")
    approval = Approval(task_id=task.id, tool_call_id="invalid", tool_name="tool", arguments={})
    with Session(engine) as session:
        TaskRepository(session).save(task)
        ApprovalRepository(session).create(approval)
    assert client.post(f"/api/approvals/{approval.id}/approve").status_code == 409
    with Session(engine) as observer:
        assert ApprovalRepository(observer).get_by_id(approval.id).status is ApprovalStatus.PENDING


def test_missing_task_context_rejected():
    approvals = Mock(spec=ApprovalRepository)
    tasks = Mock(spec=TaskRepository)
    approval = Approval(task_id=uuid4(), tool_call_id="missing", tool_name="tool", arguments={})
    approvals.get_by_id.return_value = approval
    tasks.get.return_value = None
    with pytest.raises(ApprovalTaskContextError):
        ApprovalDecisionService(approvals, tasks, Mock(spec=ApprovalRejectionPersistence), Mock(spec=ApprovalContinuationPersistence)).decide(approval.id, "reject")
    approvals.save_decision_if_pending.assert_not_called()


@pytest.mark.parametrize("decisions", [("approve", "reject"), ("approve", "approve"), ("reject", "reject")])
def test_real_concurrent_decisions_exactly_one_winner(engine, decisions):
    task, approval = seed(engine)
    barrier = Barrier(2)
    class ConcurrentRepository(ApprovalRepository):
        def get_by_id(self, approval_id):
            loaded = super().get_by_id(approval_id)
            barrier.wait(timeout=10)
            return loaded
    class ConcurrentTasks(TaskRepository):
        def get(self, task_id):
            loaded = super().get(task_id)
            barrier.wait(timeout=10)
            return loaded
    def decide(decision):
        with Session(engine) as session:
            service = ApprovalDecisionService(ConcurrentRepository(session), ConcurrentTasks(session), ApprovalRejectionPersistence(session), ApprovalContinuationPersistence(session))
            try:
                result = service.decide(approval.id, decision)
                return ("accepted", result.status, result.decided_at)
            except ApprovalDecisionConflictError:
                return ("conflict", None, None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(decide, decision) for decision in decisions]
        results = [future.result(timeout=15) for future in futures]
    assert sorted(result[0] for result in results) == ["accepted", "conflict"]
    winner = next(result for result in results if result[0] == "accepted")
    print(f"concurrency {decisions}: {results[0][0]}, {results[1][0]}; durable={winner[1].value}")
    with Session(engine) as observer:
        loaded = ApprovalRepository(observer).get_by_id(approval.id)
        assert loaded.status is winner[1]
        assert loaded.decided_at == winner[2]
        assert TaskRepository(observer).get(task.id).status is (TaskStatus.RUNNING if winner[1] is ApprovalStatus.APPROVED else TaskStatus.REJECTED)


def test_repository_rejects_pending_candidate(engine):
    _, approval = seed(engine)
    with Session(engine) as session:
        with pytest.raises(ApprovalError, match="terminal"):
            ApprovalRepository(session).save_decision_if_pending(approval)


def test_decision_statement_failure_rolls_back_and_is_not_conflict(engine, client):
    task, approval = seed(engine)
    with engine.begin() as connection:
        connection.execute(text("""CREATE FUNCTION task024_fail_decision() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'task024 persistence failure'; END; $$"""))
        connection.execute(text("""CREATE TRIGGER task024_failure BEFORE UPDATE ON approvals
            FOR EACH ROW EXECUTE FUNCTION task024_fail_decision()"""))
    try:
        with Session(engine) as session:
            service = ApprovalDecisionService(ApprovalRepository(session), TaskRepository(session), ApprovalRejectionPersistence(session), ApprovalContinuationPersistence(session))
            with pytest.raises(SQLAlchemyError, match="task024 persistence failure"):
                service.decide(approval.id, "approve")
            assert not session.in_transaction()
        assert client.post(f"/api/approvals/{approval.id}/reject").status_code == 500
        with Session(engine) as observer:
            loaded = ApprovalRepository(observer).get_by_id(approval.id)
            assert loaded.status is ApprovalStatus.PENDING
            assert loaded.decided_at is None
            assert TaskRepository(observer).get(task.id).status is TaskStatus.WAITING_APPROVAL
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TRIGGER task024_failure ON approvals"))
            connection.execute(text("DROP FUNCTION task024_fail_decision()"))

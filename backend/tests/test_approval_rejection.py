from unittest.mock import patch

import pytest
from sqlalchemy import text, event
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.orm import Session

from test_approval_decision import engine, client, seed
from app.approvals.repository import ApprovalRepository
from app.approvals.service import ApprovalDecisionService
from app.approvals.rejection_persistence import ApprovalRejectionPersistence
from app.tasks.repository import TaskRepository
from app.tasks import TaskStatus
from app.tools.base import Tool
from app.agents.runtime import AgentRuntime


def states(engine, task_id, approval_id):
    with Session(engine) as observer:
        task = TaskRepository(observer).get(task_id)
        approval = ApprovalRepository(observer).get_by_id(approval_id)
        assert task.result is None and task.error is None
        return task.status.value, approval.status.value


def test_atomic_rejection_one_commit_visibility_and_filter(engine, client):
    task, approval = seed(engine)
    commits = []
    with Session(engine) as session:
        def before_commit(current):
            commits.append(True)
            assert states(engine, task.id, approval.id) == ("WAITING_APPROVAL", "PENDING")
            assert current.execute(text("SELECT status FROM tasks WHERE id=:id"), {"id": task.id}).scalar_one() == "REJECTED"
            assert current.execute(text("SELECT status FROM approvals WHERE id=:id"), {"id": approval.id}).scalar_one() == "REJECTED"
        event.listen(session, "before_commit", before_commit)
        service = ApprovalDecisionService(ApprovalRepository(session), TaskRepository(session), ApprovalRejectionPersistence(session))
        with patch.object(Tool, "execute") as execute, patch.object(AgentRuntime, "run") as run:
            service.decide(approval.id, "reject")
            execute.assert_not_called()
            run.assert_not_called()
    assert len(commits) == 1
    assert states(engine, task.id, approval.id) == ("REJECTED", "REJECTED")
    assert client.get(f"/api/tasks/{task.id}").json()["status"] == "rejected"
    response = client.get("/api/tasks?status=rejected")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [str(task.id)]


@pytest.mark.parametrize("failure", ["approval", "task", "commit"])
def test_reject_postgresql_failure_rolls_back_both(engine, client, failure):
    task, approval = seed(engine)
    table = "tasks" if failure == "task" else "approvals"
    with engine.begin() as connection:
        connection.execute(text("""CREATE FUNCTION task025_fail() RETURNS trigger LANGUAGE plpgsql AS $$
          BEGIN RAISE EXCEPTION 'task025 failure'; END; $$"""))
        if failure == "commit":
            ddl = "CREATE CONSTRAINT TRIGGER task025_failure AFTER UPDATE ON approvals DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION task025_fail()"
        else:
            ddl = f"CREATE TRIGGER task025_failure BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION task025_fail()"
        connection.execute(text(ddl))
    try:
        with Session(engine) as session, patch.object(Tool, "execute") as execute:
            service = ApprovalDecisionService(ApprovalRepository(session), TaskRepository(session), ApprovalRejectionPersistence(session))
            with pytest.raises(SQLAlchemyError, match="task025 failure"):
                service.decide(approval.id, "reject")
            assert not session.in_transaction()
            execute.assert_not_called()
        assert states(engine, task.id, approval.id) == ("WAITING_APPROVAL", "PENDING")
        assert client.post(f"/api/approvals/{approval.id}/reject").status_code == 500
        assert states(engine, task.id, approval.id) == ("WAITING_APPROVAL", "PENDING")
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TRIGGER task025_failure ON {table}"))
            connection.execute(text("DROP FUNCTION task025_fail()"))


def test_reject_real_commit_then_ack_loss_no_fallback(engine):
    task, approval = seed(engine)
    with Session(engine) as session:
        commit = session.commit
        error = OperationalError("COMMIT", {}, RuntimeError("ack lost"))
        def lose_ack():
            commit()
            raise error
        service = ApprovalDecisionService(ApprovalRepository(session), TaskRepository(session), ApprovalRejectionPersistence(session))
        with patch.object(session, "commit", side_effect=lose_ack) as commit_call, patch.object(Tool, "execute") as execute:
            with pytest.raises(OperationalError) as raised:
                service.decide(approval.id, "reject")
            assert raised.value is error
            assert commit_call.call_count == 1
            execute.assert_not_called()
    assert states(engine, task.id, approval.id) == ("REJECTED", "REJECTED")


def test_task_conditional_rejection_blocks_terminal_overwrite(engine):
    task, approval = seed(engine)
    candidate = type(task).restore(**task.model_dump())
    candidate.mark_rejected()
    with Session(engine) as session:
        repository = TaskRepository(session)
        assert repository.stage_rejected_if_waiting(candidate) is True
        session.commit()
        assert repository.stage_rejected_if_waiting(candidate) is False
        session.rollback()

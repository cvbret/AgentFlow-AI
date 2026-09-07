import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.approvals import Approval, ApprovalError, ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.db.models import ApprovalRecord, TaskRecord
from app.tasks import Task
from app.tasks.repository import TaskRepository


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    from sqlalchemy import create_engine

    test_engine = create_engine(database_url)
    with test_engine.connect() as connection:
        inspector = inspect(connection)
        assert inspector.has_table("tasks")
        assert inspector.has_table("approvals")
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        yield db_session
        db_session.rollback()
        db_session.execute(delete(ApprovalRecord))
        db_session.execute(delete(TaskRecord))
        db_session.commit()


def make_task(session: Session) -> Task:
    task = Task(input="approval task")
    TaskRepository(session).save(task)
    return task


def make_approval(task: Task) -> Approval:
    return Approval(
        task_id=task.id,
        tool_call_id="call_123",
        tool_name="payment",
        arguments={
            "amount": {"value": 100, "currency": "CNY"},
            "notify": True,
            "recipients": ["ops@example.com"],
        },
    )


def test_create_and_get_pending_approval(session: Session) -> None:
    task = make_task(session)
    approval = make_approval(task)
    repository = ApprovalRepository(session)

    saved = repository.create(approval)
    loaded = repository.get_by_id(approval.id)

    assert saved is approval
    assert loaded is not None
    assert loaded.id == approval.id
    assert loaded.task_id == task.id
    assert loaded.tool_call_id == "call_123"
    assert loaded.tool_name == "payment"
    assert loaded.status is ApprovalStatus.PENDING
    assert loaded.decided_at is None


def test_arguments_round_trip_preserves_nested_structure(session: Session) -> None:
    task = make_task(session)
    approval = make_approval(task)
    repository = ApprovalRepository(session)

    repository.create(approval)
    loaded = repository.get_by_id(approval.id)

    assert loaded is not None
    assert loaded.arguments == approval.arguments
    assert loaded.arguments["amount"] == {
        "value": 100,
        "currency": "CNY",
    }
    assert loaded.arguments["notify"] is True
    assert loaded.arguments["recipients"] == ["ops@example.com"]


def test_approve_save_and_restore(session: Session) -> None:
    task = make_task(session)
    approval = make_approval(task)
    repository = ApprovalRepository(session)
    repository.create(approval)

    decision_time = approval.created_at + timedelta(seconds=1)
    approval.approve(now=decision_time)
    repository.save(approval)
    loaded = repository.get_by_id(approval.id)

    assert loaded is not None
    assert loaded.status is ApprovalStatus.APPROVED
    assert loaded.decided_at == decision_time


def test_reject_save_and_restore(session: Session) -> None:
    task = make_task(session)
    approval = make_approval(task)
    repository = ApprovalRepository(session)
    repository.create(approval)

    decision_time = approval.created_at + timedelta(seconds=1)
    approval.reject(now=decision_time)
    repository.save(approval)
    loaded = repository.get_by_id(approval.id)

    assert loaded is not None
    assert loaded.status is ApprovalStatus.REJECTED
    assert loaded.decided_at == decision_time


def test_get_rejects_invalid_persisted_approval_state(session: Session) -> None:
    task = make_task(session)
    approval_id = uuid4()
    now = datetime.now(timezone.utc)
    session.add(
        ApprovalRecord(
            id=approval_id,
            task_id=task.id,
            tool_call_id="call_invalid",
            tool_name="payment",
            arguments={},
            status=ApprovalStatus.APPROVED.value,
            created_at=now,
            decided_at=None,
        )
    )
    session.commit()

    with pytest.raises(ApprovalError, match="Invalid persisted Approval state"):
        ApprovalRepository(session).get_by_id(approval_id)


def test_create_enforces_task_foreign_key(session: Session) -> None:
    approval = Approval(
        task_id=uuid4(),
        tool_call_id="call_orphan",
        tool_name="payment",
        arguments={},
    )

    with pytest.raises(IntegrityError):
        ApprovalRepository(session).create(approval)


def test_create_rejects_terminal_approval() -> None:
    db_session = Mock(spec=Session)
    approval = Approval.restore(
        id=uuid4(),
        task_id=uuid4(),
        tool_call_id="call_terminal",
        tool_name="payment",
        arguments={},
        status=ApprovalStatus.APPROVED,
        created_at=datetime.now(timezone.utc),
        decided_at=datetime.now(timezone.utc),
    )

    with pytest.raises(ApprovalError, match="requires PENDING"):
        ApprovalRepository(db_session).create(approval)

    db_session.add.assert_not_called()
    db_session.commit.assert_not_called()


def test_create_rolls_back_when_add_fails() -> None:
    db_session = Mock(spec=Session)
    db_session.add.side_effect = SQLAlchemyError("add failed")
    approval = Approval(
        task_id=uuid4(),
        tool_call_id="call_add_failure",
        tool_name="payment",
        arguments={},
    )

    with pytest.raises(SQLAlchemyError, match="add failed"):
        ApprovalRepository(db_session).create(approval)

    db_session.rollback.assert_called_once_with()
    db_session.close.assert_not_called()


def test_save_commit_failure_rolls_back_and_session_can_be_reused() -> None:
    db_session = Mock(spec=Session)
    db_session.get.return_value = None
    db_session.commit.side_effect = [
        SQLAlchemyError("commit failed"),
        None,
    ]
    repository = ApprovalRepository(db_session)
    approval = Approval(
        task_id=uuid4(),
        tool_call_id="call_commit_failure",
        tool_name="payment",
        arguments={},
    )

    with pytest.raises(SQLAlchemyError, match="commit failed"):
        repository.save(approval)

    saved = repository.save(approval)

    assert saved is approval
    db_session.rollback.assert_called_once_with()
    assert db_session.commit.call_count == 2
    db_session.close.assert_not_called()

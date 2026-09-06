import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import TaskRecord
from app.tasks import Task, TaskError, TaskStatus
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
        assert inspect(connection).has_table("tasks")
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        yield db_session
        db_session.rollback()
        db_session.execute(delete(TaskRecord))
        db_session.commit()


def test_save_and_get_pending_task(session: Session) -> None:
    task = Task(input="hello")
    repository = TaskRepository(session)

    saved = repository.save(task)
    loaded = repository.get(task.id)

    assert saved.id == task.id
    assert loaded is not None
    assert loaded.id == task.id
    assert loaded.status is TaskStatus.PENDING
    assert loaded.input == "hello"
    assert loaded.result is None
    assert loaded.error is None


def test_save_and_get_running_task(session: Session) -> None:
    task = Task(input="run")
    task.start()
    repository = TaskRepository(session)

    repository.save(task)
    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.status is TaskStatus.RUNNING


def test_save_and_get_succeeded_task(session: Session) -> None:
    task = Task(input="calculate")
    task.start()
    task.succeed("42")
    repository = TaskRepository(session)

    repository.save(task)
    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.status is TaskStatus.SUCCEEDED
    assert loaded.result == "42"
    assert loaded.error is None


def test_save_and_get_failed_task(session: Session) -> None:
    task = Task(input="fail")
    task.start()
    task.fail("provider unavailable")
    repository = TaskRepository(session)

    repository.save(task)
    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.status is TaskStatus.FAILED
    assert loaded.result is None
    assert loaded.error == "provider unavailable"


def test_persisted_timestamps_are_utc_and_preserved(session: Session) -> None:
    task = Task(input="timestamps")
    repository = TaskRepository(session)

    repository.save(task)
    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.created_at.tzinfo is not None
    assert loaded.updated_at.tzinfo is not None
    assert loaded.created_at.utcoffset() == timedelta(0)
    assert loaded.updated_at.utcoffset() == timedelta(0)
    assert loaded.created_at == task.created_at
    assert loaded.updated_at == task.updated_at


def test_get_missing_task_returns_none(session: Session) -> None:
    assert TaskRepository(session).get(uuid4()) is None


def _listing_task(index: int, created_at: datetime) -> Task:
    return Task(
        id=UUID(int=index),
        input=f"task-{index}",
        created_at=created_at,
        updated_at=created_at,
    )


def _task_with_status(index: int, created_at: datetime, status: TaskStatus) -> Task:
    task = _listing_task(index, created_at)
    if status is TaskStatus.RUNNING:
        task.start(now=created_at)
    elif status is TaskStatus.SUCCEEDED:
        task.start(now=created_at)
        task.succeed(f"result-{index}", now=created_at)
    elif status is TaskStatus.FAILED:
        task.start(now=created_at)
        task.fail(f"error-{index}", now=created_at)
    return task


def test_list_returns_empty_list_when_no_tasks_exist(session: Session) -> None:
    assert TaskRepository(session).list(20, 0) == []


def test_list_returns_domain_tasks_in_stable_newest_first_order(session: Session) -> None:
    repository = TaskRepository(session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    timestamps = (
        (1, base),
        (2, base + timedelta(seconds=1)),
        (3, base + timedelta(seconds=1)),
    )
    for index, created_at in timestamps:
        repository.save(_listing_task(index, created_at))

    result = repository.list(10, 0)

    assert [task.id for task in result] == [UUID(int=3), UUID(int=2), UUID(int=1)]
    assert all(isinstance(task, Task) for task in result)


def test_list_applies_limit_and_offset(session: Session) -> None:
    repository = TaskRepository(session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(1, 5):
        repository.save(_listing_task(index, base + timedelta(seconds=index)))

    assert [task.id for task in repository.list(2, 0)] == [UUID(int=4), UUID(int=3)]
    assert [task.id for task in repository.list(2, 2)] == [UUID(int=2), UUID(int=1)]


def test_list_pages_do_not_duplicate_tasks(session: Session) -> None:
    repository = TaskRepository(session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(1, 4):
        repository.save(_listing_task(index, base))

    first_page = repository.list(2, 0)
    second_page = repository.list(2, 2)

    assert {task.id for task in first_page}.isdisjoint({task.id for task in second_page})
    assert len(first_page) + len(second_page) == 3


def test_list_without_status_returns_tasks_in_all_states(session: Session) -> None:
    repository = TaskRepository(session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tasks = [
        _task_with_status(11, base, TaskStatus.PENDING),
        _task_with_status(12, base, TaskStatus.RUNNING),
        _task_with_status(13, base, TaskStatus.SUCCEEDED),
        _task_with_status(14, base, TaskStatus.FAILED),
    ]
    for task in tasks:
        repository.save(task)

    result = repository.list(20, 0, None)

    assert {task.status for task in result} == set(TaskStatus)


def test_list_filters_failed_tasks_in_sql_query(session: Session) -> None:
    repository = TaskRepository(session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tasks = [
        _task_with_status(21, base, TaskStatus.FAILED),
        _task_with_status(22, base, TaskStatus.SUCCEEDED),
        _task_with_status(23, base, TaskStatus.FAILED),
    ]
    for task in tasks:
        repository.save(task)

    result = repository.list(20, 0, TaskStatus.FAILED)

    assert [task.id for task in result] == [UUID(int=23), UUID(int=21)]
    assert all(task.status is TaskStatus.FAILED for task in result)


def test_list_filters_succeeded_tasks(session: Session) -> None:
    repository = TaskRepository(session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, status in ((31, TaskStatus.SUCCEEDED), (32, TaskStatus.FAILED)):
        repository.save(_task_with_status(index, base, status))

    result = repository.list(20, 0, TaskStatus.SUCCEEDED)

    assert [task.id for task in result] == [UUID(int=31)]
    assert result[0].status is TaskStatus.SUCCEEDED


def test_list_applies_limit_and_offset_after_status_filter(session: Session) -> None:
    repository = TaskRepository(session)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in (41, 42, 43):
        repository.save(_task_with_status(index, base, TaskStatus.FAILED))
    repository.save(_task_with_status(44, base, TaskStatus.SUCCEEDED))

    result = repository.list(1, 1, TaskStatus.FAILED)

    assert [task.id for task in result] == [UUID(int=42)]
    assert result[0].status is TaskStatus.FAILED


def test_multiple_tasks_remain_independent(session: Session) -> None:
    first = Task(input="first")
    second = Task(input="second")
    repository = TaskRepository(session)

    repository.save(first)
    repository.save(second)

    loaded_first = repository.get(first.id)
    loaded_second = repository.get(second.id)

    assert loaded_first is not None
    assert loaded_second is not None
    assert loaded_first.id != loaded_second.id
    assert loaded_first.input == "first"
    assert loaded_second.input == "second"


def test_save_existing_task_updates_record(session: Session) -> None:
    task = Task(input="update")
    repository = TaskRepository(session)
    repository.save(task)

    task.start()
    task.succeed("updated")
    repository.save(task)
    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.status is TaskStatus.SUCCEEDED
    assert loaded.result == "updated"


def test_repository_rehydrates_succeeded_task(session: Session) -> None:
    task = Task(input="rehydrate")
    task.start()
    task.succeed("done")
    repository = TaskRepository(session)
    repository.save(task)

    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.status is TaskStatus.SUCCEEDED
    assert loaded.result == "done"
    assert loaded.created_at == task.created_at
    assert loaded.updated_at == task.updated_at


def test_repository_rehydrates_failed_task(session: Session) -> None:
    task = Task(input="rehydrate failure")
    task.start()
    task.fail("failed")
    repository = TaskRepository(session)
    repository.save(task)

    loaded = repository.get(task.id)

    assert loaded is not None
    assert loaded.status is TaskStatus.FAILED
    assert loaded.error == "failed"


def test_invalid_persisted_state_is_rejected(session: Session) -> None:
    now = datetime.now(timezone.utc)
    task_id = uuid4()
    session.add(
        TaskRecord(
            id=task_id,
            status=TaskStatus.SUCCEEDED.value,
            input="invalid",
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()

    with pytest.raises(TaskError, match="Invalid persisted Task state"):
        TaskRepository(session).get(task_id)


def test_save_rolls_back_when_session_get_fails() -> None:
    db_session = Mock(spec=Session)
    db_session.get.side_effect = SQLAlchemyError("get failed")

    with pytest.raises(SQLAlchemyError, match="get failed"):
        TaskRepository(db_session).save(Task(input="get failure"))

    db_session.rollback.assert_called_once_with()
    db_session.close.assert_not_called()


def test_save_rolls_back_when_add_fails() -> None:
    db_session = Mock(spec=Session)
    db_session.get.return_value = None
    db_session.add.side_effect = SQLAlchemyError("add failed")

    with pytest.raises(SQLAlchemyError, match="add failed"):
        TaskRepository(db_session).save(Task(input="add failure"))

    db_session.rollback.assert_called_once_with()
    db_session.close.assert_not_called()


def test_commit_failure_rolls_back_and_session_can_be_reused() -> None:
    db_session = Mock(spec=Session)
    db_session.get.return_value = None
    db_session.commit.side_effect = [
        SQLAlchemyError("commit failed"),
        None,
    ]
    repository = TaskRepository(db_session)

    with pytest.raises(SQLAlchemyError, match="commit failed"):
        repository.save(Task(input="commit failure"))

    saved = repository.save(Task(input="after rollback"))

    assert saved.input == "after rollback"
    db_session.rollback.assert_called_once_with()
    assert db_session.commit.call_count == 2
    db_session.close.assert_not_called()


def test_save_does_not_depend_on_post_commit_refresh() -> None:
    db_session = Mock(spec=Session)
    db_session.get.return_value = None

    saved = TaskRepository(db_session).save(Task(input="no refresh"))

    assert saved.input == "no refresh"
    db_session.refresh.assert_not_called()

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.tasks import (
    InvalidTaskStateTransitionError,
    Task,
    TaskError,
    TaskStatus,
)


def make_task() -> Task:
    return Task(input="计算 12 × 8")


def test_new_task_has_pending_state_and_utc_timestamps() -> None:
    task = make_task()

    assert isinstance(task.id, UUID)
    assert task.status is TaskStatus.PENDING
    assert task.result is None
    assert task.error is None
    assert task.created_at.tzinfo is not None
    assert task.updated_at.tzinfo is not None
    assert task.created_at.utcoffset() == timedelta(0)
    assert task.updated_at.utcoffset() == timedelta(0)
    assert task.created_at <= task.updated_at


def test_start_transitions_pending_to_running() -> None:
    task = make_task()
    timestamp = task.updated_at + timedelta(seconds=1)

    task.start(now=timestamp)

    assert task.status is TaskStatus.RUNNING
    assert task.result is None
    assert task.error is None
    assert task.updated_at == timestamp


def test_succeed_transitions_running_to_succeeded_with_result() -> None:
    task = make_task()
    task.start()
    timestamp = task.updated_at + timedelta(seconds=1)

    task.succeed("96", now=timestamp)

    assert task.status is TaskStatus.SUCCEEDED
    assert task.result == "96"
    assert task.error is None
    assert task.updated_at == timestamp


def test_fail_transitions_running_to_failed_with_error() -> None:
    task = make_task()
    task.start()
    timestamp = task.updated_at + timedelta(seconds=1)

    task.fail("provider unavailable", now=timestamp)

    assert task.status is TaskStatus.FAILED
    assert task.result is None
    assert task.error == "provider unavailable"
    assert task.updated_at == timestamp


@pytest.mark.parametrize(
    "method",
    [
        lambda task: task.succeed("96"),
        lambda task: task.fail("failed"),
    ],
)
def test_pending_task_cannot_complete_directly(method) -> None:
    with pytest.raises(InvalidTaskStateTransitionError):
        method(make_task())


@pytest.mark.parametrize(
    "method",
    [
        lambda task: task.start(),
        lambda task: task.succeed("again"),
        lambda task: task.fail("again"),
    ],
)
def test_succeeded_task_is_terminal(method) -> None:
    task = make_task()
    task.start()
    task.succeed("done")

    with pytest.raises(InvalidTaskStateTransitionError):
        method(task)


@pytest.mark.parametrize(
    "method",
    [
        lambda task: task.start(),
        lambda task: task.succeed("again"),
        lambda task: task.fail("again"),
    ],
)
def test_failed_task_is_terminal(method) -> None:
    task = make_task()
    task.start()
    task.fail("failed")

    with pytest.raises(InvalidTaskStateTransitionError):
        method(task)


def test_status_cannot_be_changed_by_direct_assignment() -> None:
    task = make_task()

    with pytest.raises(AttributeError):
        task.status = TaskStatus.RUNNING


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("result", "illegal"),
        ("error", "illegal"),
        ("created_at", datetime.now(timezone.utc)),
        ("updated_at", datetime.now(timezone.utc)),
        ("input", "changed"),
    ],
)
def test_lifecycle_fields_cannot_be_changed_by_direct_assignment(
    field: str,
    value: object,
) -> None:
    task = make_task()

    with pytest.raises(AttributeError):
        setattr(task, field, value)


def test_lifecycle_methods_can_mutate_protected_fields() -> None:
    task = make_task()
    task.start()
    task.succeed("96")

    assert task.status is TaskStatus.SUCCEEDED
    assert task.result == "96"
    assert task.error is None


def test_transition_updates_timestamp_without_sleep() -> None:
    task = make_task()
    previous = task.updated_at
    transition_time = previous + timedelta(seconds=1)

    task.start(now=transition_time)

    assert task.updated_at >= previous


@pytest.mark.parametrize("method", ["start", "succeed", "fail"])
def test_transitions_reject_backward_timestamps(method: str) -> None:
    task = make_task()
    if method != "start":
        task.start()
    timestamp = task.updated_at - timedelta(seconds=1)

    with pytest.raises(TaskError, match="cannot move backwards"):
        if method == "start":
            task.start(now=timestamp)
        elif method == "succeed":
            task.succeed("done", now=timestamp)
        else:
            task.fail("failed", now=timestamp)


@pytest.mark.parametrize("method", ["start", "succeed", "fail"])
def test_equal_transition_timestamp_is_allowed(method: str) -> None:
    task = make_task()
    if method != "start":
        task.start()
    timestamp = task.updated_at

    if method == "start":
        task.start(now=timestamp)
    elif method == "succeed":
        task.succeed("done", now=timestamp)
    else:
        task.fail("failed", now=timestamp)

    assert task.updated_at == timestamp


@pytest.mark.parametrize("result", [None, "", "   ", "\n"])
def test_succeed_rejects_empty_or_whitespace_result(
    result: str | None,
) -> None:
    task = make_task()
    task.start()

    with pytest.raises(TaskError, match="non-empty string"):
        task.succeed(result)


def test_succeed_accepts_non_empty_result() -> None:
    task = make_task()
    task.start()

    task.succeed("96")

    assert task.status is TaskStatus.SUCCEEDED
    assert task.result == "96"


@pytest.mark.parametrize("error", [None, "", "   ", "\n"])
def test_fail_rejects_empty_or_whitespace_error(
    error: str | None,
) -> None:
    task = make_task()
    task.start()

    with pytest.raises(TaskError, match="non-empty string"):
        task.fail(error)


def test_task_ids_are_unique() -> None:
    tasks = [make_task() for _ in range(10)]

    assert len({task.id for task in tasks}) == len(tasks)


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Task(
            input="task",
            created_at=datetime(2026, 1, 1),
        )


def test_domain_invariants_reject_non_initial_state_values() -> None:
    with pytest.raises(ValidationError):
        Task(input="task", result="unexpected")


@pytest.mark.parametrize(
    ("status", "result", "error"),
    [
        (TaskStatus.SUCCEEDED, None, None),
        (TaskStatus.FAILED, None, None),
        (TaskStatus.RUNNING, "unexpected", None),
        (TaskStatus.RUNNING, None, "unexpected"),
    ],
)
def test_constructor_rejects_invalid_lifecycle_state(
    status: TaskStatus,
    result: str | None,
    error: str | None,
) -> None:
    with pytest.raises(ValidationError):
        Task(input="task", status=status, result=result, error=error)

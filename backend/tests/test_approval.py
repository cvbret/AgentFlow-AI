from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.approvals import (
    Approval,
    ApprovalError,
    ApprovalStatus,
    InvalidApprovalStateTransitionError,
)


def make_arguments() -> dict[str, object]:
    return {"operation": "charge", "amount": {"value": 100}}


def make_approval(
    *,
    arguments: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> Approval:
    return Approval(
        task_id=uuid4(),
        tool_call_id="call_123",
        tool_name="payment",
        arguments=arguments or make_arguments(),
        created_at=created_at or datetime.now(timezone.utc),
    )


def test_new_approval_is_pending_with_utc_creation_time() -> None:
    approval = make_approval()

    assert approval.id
    assert approval.status is ApprovalStatus.PENDING
    assert approval.created_at.tzinfo is not None
    assert approval.created_at.utcoffset() == timedelta(0)
    assert approval.decided_at is None


def test_approval_preserves_task_and_tool_call_identity() -> None:
    task_id = uuid4()
    approval = Approval(
        task_id=task_id,
        tool_call_id="call_abc",
        tool_name="payment",
        arguments={"amount": 100},
    )

    assert approval.task_id == task_id
    assert approval.tool_call_id == "call_abc"
    assert approval.tool_name == "payment"
    assert approval.arguments == {"amount": 100}


def test_approval_copies_arguments_snapshot() -> None:
    arguments = make_arguments()
    approval = make_approval(arguments=arguments)

    arguments["amount"]["value"] = 999

    assert approval.arguments["amount"] == {"value": 100}


def test_approve_transitions_pending_to_approved() -> None:
    approval = make_approval()
    decision_time = approval.created_at + timedelta(seconds=1)

    approval.approve(now=decision_time)

    assert approval.status is ApprovalStatus.APPROVED
    assert approval.decided_at == decision_time
    assert approval.decided_at.utcoffset() == timedelta(0)


def test_reject_transitions_pending_to_rejected() -> None:
    approval = make_approval()
    decision_time = approval.created_at + timedelta(seconds=1)

    approval.reject(now=decision_time)

    assert approval.status is ApprovalStatus.REJECTED
    assert approval.decided_at == decision_time
    assert approval.decided_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize(
    "transition",
    [
        lambda approval: approval.reject(),
        lambda approval: approval.approve(),
    ],
)
def test_approved_approval_is_terminal(transition) -> None:
    approval = make_approval()
    approval.approve()

    with pytest.raises(InvalidApprovalStateTransitionError):
        transition(approval)


@pytest.mark.parametrize(
    "transition",
    [
        lambda approval: approval.approve(),
        lambda approval: approval.reject(),
    ],
)
def test_rejected_approval_is_terminal(transition) -> None:
    approval = make_approval()
    approval.reject()

    with pytest.raises(InvalidApprovalStateTransitionError):
        transition(approval)


def test_pending_approval_cannot_have_decided_at() -> None:
    with pytest.raises(ValueError, match="new PENDING Approvals"):
        Approval(
            task_id=uuid4(),
            tool_call_id="call_123",
            tool_name="payment",
            arguments={},
            decided_at=datetime.now(timezone.utc),
        )


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_new_approval_cannot_be_created_in_terminal_state(
    status: ApprovalStatus,
) -> None:
    with pytest.raises(ValueError, match="new Approvals must start in PENDING"):
        Approval(
            task_id=uuid4(),
            tool_call_id="call_123",
            tool_name="payment",
            arguments={},
            status=status,
            decided_at=datetime.now(timezone.utc),
        )


def test_restore_pending_approval() -> None:
    created_at = datetime.now(timezone.utc)

    approval = Approval.restore(
        id=uuid4(),
        task_id=uuid4(),
        tool_call_id="call_pending",
        tool_name="payment",
        arguments={"amount": 100},
        status=ApprovalStatus.PENDING,
        created_at=created_at,
        decided_at=None,
    )

    assert approval.status is ApprovalStatus.PENDING
    assert approval.decided_at is None


@pytest.mark.parametrize("status", [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED])
def test_restore_terminal_approval(status: ApprovalStatus) -> None:
    created_at = datetime.now(timezone.utc)
    decided_at = created_at + timedelta(seconds=1)

    approval = Approval.restore(
        id=uuid4(),
        task_id=uuid4(),
        tool_call_id="call_terminal",
        tool_name="payment",
        arguments={"amount": 100},
        status=status,
        created_at=created_at,
        decided_at=decided_at,
    )

    assert approval.status is status
    assert approval.decided_at == decided_at


def test_restore_rejects_terminal_approval_without_decision_time() -> None:
    with pytest.raises(ApprovalError, match="Invalid persisted Approval state"):
        Approval.restore(
            id=uuid4(),
            task_id=uuid4(),
            tool_call_id="call_approved",
            tool_name="payment",
            arguments={},
            status=ApprovalStatus.APPROVED,
            created_at=datetime.now(timezone.utc),
            decided_at=None,
        )


def test_restore_rejects_pending_approval_with_decision_time() -> None:
    with pytest.raises(ApprovalError, match="Invalid persisted Approval state"):
        Approval.restore(
            id=uuid4(),
            task_id=uuid4(),
            tool_call_id="call_pending",
            tool_name="payment",
            arguments={},
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            decided_at=datetime.now(timezone.utc),
        )


def test_decision_cannot_precede_creation_time() -> None:
    created_at = datetime.now(timezone.utc)
    approval = make_approval(created_at=created_at)

    with pytest.raises(ApprovalError, match="earlier than created_at"):
        approval.approve(now=created_at - timedelta(seconds=1))

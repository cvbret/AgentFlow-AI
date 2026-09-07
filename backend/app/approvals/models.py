from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)

from app.approvals.exceptions import (
    ApprovalError,
    InvalidApprovalStateTransitionError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Approval timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Approval(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)
    decided_at: datetime | None = None

    _PROTECTED_FIELDS = frozenset(
        {
            "task_id",
            "tool_call_id",
            "tool_name",
            "arguments",
            "status",
            "created_at",
            "decided_at",
        }
    )

    def __init__(self, **data: Any) -> None:
        requested_status = data.get("status", ApprovalStatus.PENDING)
        if ApprovalStatus(requested_status) is not ApprovalStatus.PENDING:
            raise ValueError("new Approvals must start in PENDING state")
        if data.get("decided_at") is not None:
            raise ValueError("new PENDING Approvals must not have decided_at")
        super().__init__(**data)

    @classmethod
    def restore(
        cls,
        *,
        id: UUID,
        task_id: UUID,
        tool_call_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        status: ApprovalStatus,
        created_at: datetime,
        decided_at: datetime | None,
    ) -> "Approval":
        approval = cls(
            id=id,
            task_id=task_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=arguments,
            created_at=created_at,
        )
        restored_status = ApprovalStatus(status)
        restored_decided_at = (
            None if decided_at is None else _as_utc(decided_at)
        )
        object.__setattr__(approval, "status", restored_status)
        object.__setattr__(approval, "decided_at", restored_decided_at)
        try:
            approval.validate_state()
        except ValueError as exc:
            raise ApprovalError("Invalid persisted Approval state") from exc
        return approval

    @field_validator("created_at", "decided_at")
    @classmethod
    def validate_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _as_utc(value)

    @field_validator("arguments", mode="before")
    @classmethod
    def snapshot_arguments(cls, value: object) -> object:
        if isinstance(value, dict):
            return deepcopy(value)
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "Approval":
        if self.status is ApprovalStatus.PENDING and self.decided_at is not None:
            raise ValueError("PENDING Approvals must not have decided_at")
        if (
            self.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED)
            and self.decided_at is None
        ):
            raise ValueError(
                "APPROVED and REJECTED Approvals must have decided_at"
            )
        if self.decided_at is not None and self.decided_at < self.created_at:
            raise ValueError("decided_at must not be earlier than created_at")
        return self

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._PROTECTED_FIELDS and name in self.__dict__:
            raise AttributeError(
                f"Approval field '{name}' must be changed through decision methods"
            )
        super().__setattr__(name, value)

    def approve(self, *, now: datetime | None = None) -> None:
        self._decide(ApprovalStatus.APPROVED, now=now)

    def reject(self, *, now: datetime | None = None) -> None:
        self._decide(ApprovalStatus.REJECTED, now=now)

    def _decide(
        self,
        target: ApprovalStatus,
        *,
        now: datetime | None,
    ) -> None:
        if self.status is not ApprovalStatus.PENDING:
            raise InvalidApprovalStateTransitionError(
                f"Cannot transition Approval from {self.status.value} to "
                f"{target.value}"
            )

        timestamp = _as_utc(now or utc_now())
        if timestamp < self.created_at:
            raise ApprovalError(
                "Approval decided_at cannot be earlier than created_at"
            )

        object.__setattr__(self, "status", target)
        object.__setattr__(self, "decided_at", timestamp)

from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.tasks.exceptions import (
    InvalidTaskStateTransitionError,
    TaskError,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Task timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Task(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    status: TaskStatus = TaskStatus.PENDING
    input: str
    result: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    _PROTECTED_FIELDS = frozenset(
        {"input", "status", "result", "error", "created_at", "updated_at"}
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        return _as_utc(value)

    @model_validator(mode="after")
    def validate_initial_state(self) -> "Task":
        if self.status is not TaskStatus.PENDING:
            raise ValueError("new Tasks must start in PENDING state")
        if self.result is not None or self.error is not None:
            raise ValueError("new Tasks must not have result or error")
        if self.created_at > self.updated_at:
            raise ValueError("created_at must not be later than updated_at")
        return self

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._PROTECTED_FIELDS and name in self.__dict__:
            raise AttributeError(
                f"Task field '{name}' must be changed through lifecycle methods"
            )
        super().__setattr__(name, value)

    def start(self, *, now: datetime | None = None) -> None:
        self._require_state(TaskStatus.PENDING, TaskStatus.RUNNING)
        timestamp = self._transition_timestamp(now)
        object.__setattr__(self, "result", None)
        object.__setattr__(self, "error", None)
        object.__setattr__(self, "status", TaskStatus.RUNNING)
        object.__setattr__(self, "updated_at", timestamp)

    def succeed(self, result: str, *, now: datetime | None = None) -> None:
        if not isinstance(result, str) or not result.strip():
            raise TaskError("Task result must be a non-empty string")
        self._require_state(TaskStatus.RUNNING, TaskStatus.SUCCEEDED)
        timestamp = self._transition_timestamp(now)
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "error", None)
        object.__setattr__(self, "status", TaskStatus.SUCCEEDED)
        object.__setattr__(self, "updated_at", timestamp)

    def fail(self, error: str, *, now: datetime | None = None) -> None:
        if not isinstance(error, str) or not error.strip():
            raise TaskError("Task error must be a non-empty string")
        self._require_state(TaskStatus.RUNNING, TaskStatus.FAILED)
        timestamp = self._transition_timestamp(now)
        object.__setattr__(self, "result", None)
        object.__setattr__(self, "error", error)
        object.__setattr__(self, "status", TaskStatus.FAILED)
        object.__setattr__(self, "updated_at", timestamp)

    def _transition_timestamp(self, now: datetime | None) -> datetime:
        timestamp = _as_utc(now or utc_now())
        if timestamp < self.updated_at:
            raise TaskError("Task updated_at cannot move backwards")
        return timestamp

    def _require_state(
        self,
        expected: TaskStatus,
        target: TaskStatus,
    ) -> None:
        if self.status is not expected:
            raise InvalidTaskStateTransitionError(
                f"Cannot transition Task from {self.status.value} to {target.value}"
            )

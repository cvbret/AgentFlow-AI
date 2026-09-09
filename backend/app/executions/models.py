from copy import deepcopy
from datetime import datetime, timezone
from enum import StrEnum
import json
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


def canonical_arguments(arguments: dict) -> str:
    """Stable JSON identity; reject non-JSON numeric values rather than guess."""
    return json.dumps(arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class ExecutionStatus(StrEnum):
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class ToolExecution(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    approval_id: UUID
    tool_call_id: str = Field(min_length=1, max_length=255)
    tool_name: str = Field(min_length=1, max_length=255)
    arguments: dict[str, Any]
    status: ExecutionStatus = ExecutionStatus.EXECUTING
    idempotency_key: str = ""
    result_content: str | None = None
    error_code: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("arguments")
    @classmethod
    def snapshot(cls, value):
        canonical_arguments(value)
        return deepcopy(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Execution timestamps must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def invariants(self, info: ValidationInfo):
        if not (info.context and info.context.get("restore")) and self.status is not ExecutionStatus.EXECUTING:
            raise ValueError("New executions must start EXECUTING")
        if not self.idempotency_key:
            object.__setattr__(self, "idempotency_key", str(self.id))
        if self.idempotency_key != str(self.id):
            raise ValueError("Idempotency key must equal execution identity")
        if self.updated_at < self.created_at:
            raise ValueError("Execution timestamps cannot move backwards")
        if self.status is ExecutionStatus.SUCCEEDED:
            if self.result_content is None or self.error_code is not None:
                raise ValueError("SUCCEEDED requires a result and no error")
        elif self.result_content is not None:
            raise ValueError("Only SUCCEEDED can have a result")
        if self.status in (ExecutionStatus.FAILED, ExecutionStatus.UNKNOWN):
            if not self.error_code:
                raise ValueError("Unsuccessful terminal executions require an error code")
        elif self.error_code is not None:
            raise ValueError("Execution has an unexpected error code")
        return self

    @classmethod
    def restore(cls, **data):
        return cls.model_validate(data, context={"restore": True})

    def finish(self, status: ExecutionStatus, *, result_content=None, error_code=None):
        if self.status is not ExecutionStatus.EXECUTING or status is ExecutionStatus.EXECUTING:
            raise ValueError("Only EXECUTING can transition to a terminal state")
        return self.restore(**{**self.model_dump(), "status": status,
            "result_content": result_content, "error_code": error_code,
            "updated_at": max(self.updated_at, datetime.now(timezone.utc))})

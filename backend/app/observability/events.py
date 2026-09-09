"""Version-one safe event schema. Unknown attributes are dropped, never stringified."""
from datetime import datetime, timezone
import math
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

EVENT_NAMES = frozenset({
    "task.created", "task.state_changed", "task.completed",
    "approval.requested", "approval.decided",
    "tool.execution.claimed", "tool.execution.cache_hit", "tool.execution.succeeded",
    "tool.execution.failed", "tool.execution.unknown",
    "workflow.paused", "workflow.resumed",
    "recovery.started", "recovery.completed",
    "llm.request.started", "llm.request.succeeded", "llm.request.failed", "llm.retry.scheduled",
})
_SYMBOL = re.compile(r"[A-Za-z0-9_.:/-]{1,128}\Z")
_STATUSES = frozenset({"PENDING", "RUNNING", "WAITING_APPROVAL", "SUCCEEDED", "FAILED",
                       "REJECTED", "RECOVERY_REQUIRED", "APPROVED", "EXECUTING", "UNKNOWN"})
_OUTCOMES = _STATUSES | frozenset({"started", "succeeded", "failed", "scheduled", "resumed", "paused",
    "recovered", "no_action", "still_in_progress", "recovery_required", "orphan_checkpoint"})


def safe_attributes(values: object) -> dict:
    if not isinstance(values, dict):
        return {}
    result = {}
    for key, value in values.items():
        if key in {"attempt", "max_attempts", "argument_count"} and type(value) is int and value >= 0:
            result[key] = value
        elif key == "delay_seconds" and type(value) in (int, float) and math.isfinite(value) and value >= 0:
            result[key] = value
        elif key == "retryable" and type(value) is bool:
            result[key] = value
        elif key in {"from_status", "to_status", "status"} and isinstance(value, str) and value in _STATUSES:
            result[key] = str(value)
        elif key == "decision" and value in ("approve", "reject"):
            result[key] = value
        elif key == "idempotency_mode" and value in ("NONE", "EXTERNAL_KEY", "INHERENT", "unavailable"):
            result[key] = str(value)
        elif key in {"model", "tool_name", "exception_type"} and isinstance(value, str) and _SYMBOL.fullmatch(value):
            result[key] = value
        elif key == "error_category" and value in ("provider", "invalid_response", "unexpected", "known_no_effect", "outcome_unknown"):
            result[key] = value
    return result


class ObservabilityEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    event_name: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: Literal["INFO", "WARNING", "ERROR"] = "INFO"
    request_id: UUID | None = None
    task_id: UUID | None = None
    thread_id: UUID | None = None
    approval_id: UUID | None = None
    execution_id: UUID | None = None
    tool_call_id: str | None = None
    component: Literal["task", "approval", "execution", "workflow", "recovery", "llm"]
    outcome: str | None = None
    attributes: dict = Field(default_factory=dict)

    @field_validator("event_name")
    @classmethod
    def known_event(cls, value):
        if value not in EVENT_NAMES:
            raise ValueError("Unknown observability event")
        return value

    @field_validator("outcome")
    @classmethod
    def known_outcome(cls, value):
        if value is not None and value not in _OUTCOMES:
            raise ValueError("Unknown observability outcome")
        return value

    @field_validator("tool_call_id")
    @classmethod
    def safe_call_id(cls, value):
        if value is not None and not _SYMBOL.fullmatch(value):
            raise ValueError("Invalid correlation token")
        return value

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware timestamp required")
        return value.astimezone(timezone.utc)

    @field_validator("attributes", mode="before")
    @classmethod
    def sanitized(cls, value):
        return safe_attributes(value)

    def to_json(self) -> str:
        # Revalidation prevents a mutated attributes dictionary bypassing the policy.
        return type(self).model_validate(self.model_dump()).model_dump_json()

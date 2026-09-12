"""Future payload-free telemetry contract, not an event bus or active sink."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CommunicationEventName(StrEnum):
    SENT = "agent.message.sent"
    RECEIVED = "agent.message.received"
    HANDOFF_STARTED = "agent.handoff.started"
    DELEGATION_STARTED = "agent.delegation.started"
    DELEGATION_COMPLETED = "agent.delegation.completed"


class CommunicationEvent(BaseModel):
    """Future adapter input following TASK-031 naming and UTC correlation style.

    Not accepted by the current ObservabilityEvent allowlist. Delivery integration
    requires a separately reviewed adapter. No body, artifact or metadata payload
    is accepted; constructing this object does not attest that delivery occurred.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_name: CommunicationEventName
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    level: Literal["INFO"] = "INFO"
    component: Literal["agent"] = "agent"
    task_id: UUID
    message_id: UUID
    request_id: UUID | None = None

    @field_validator("timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware timestamp required")
        return value.astimezone(timezone.utc)

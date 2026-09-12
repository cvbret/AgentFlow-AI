"""Descriptive Agent-to-Agent message; no delivery or authorization."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.agents.models import NonBlankString
from app.agents.communication.artifacts import Artifact
from app.agents.communication.types import MessageType


class AgentMessage(BaseModel):
    """IDs correlate domain objects; they do not prove identity or permission."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    message_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    sender_agent_id: NonBlankString
    receiver_agent_id: NonBlankString
    message_type: MessageType
    content: NonBlankString
    artifacts: tuple[Artifact, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("artifacts", "metadata", mode="before")
    @classmethod
    def snapshot(cls, value):
        return deepcopy(value)

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timezone-aware timestamp required")
        return value.astimezone(timezone.utc)

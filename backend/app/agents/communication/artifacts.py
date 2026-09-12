"""In-memory artifact contracts; no storage or file access."""
from copy import deepcopy
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator

from app.agents.models import NonBlankString
from app.agents.communication.types import ArtifactType


class Artifact(BaseModel):
    """Inline structured payload; metadata is copied, not deeply immutable."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    artifact_id: UUID = Field(default_factory=uuid4)
    artifact_type: ArtifactType
    name: NonBlankString
    content: JsonValue
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("content", "metadata", mode="before")
    @classmethod
    def snapshot(cls, value):
        return deepcopy(value)

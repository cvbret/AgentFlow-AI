"""Runtime-independent descriptive Agent model."""

from copy import deepcopy
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictStr, field_validator


NonBlankString = Annotated[StrictStr, Field(min_length=1, pattern=r"\S")]


class Agent(BaseModel):
    """Describe a role and its requested tools; never execute or authorize effects.

    Fields cannot be reassigned and tool grants are immutable. Metadata is a
    defensive JSON snapshot, not deeply immutable and never permission data.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    name: NonBlankString
    role: NonBlankString
    system_prompt: NonBlankString
    allowed_tools: frozenset[NonBlankString] = Field(default_factory=frozenset)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def snapshot_metadata(cls, value):
        return deepcopy(value)

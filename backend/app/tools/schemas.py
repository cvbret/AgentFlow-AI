from typing import Any
from enum import StrEnum

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    content: str


class ToolExecutionResult(BaseModel):
    tool_call_id: str
    tool_name: str
    content: str


class IdempotencyMode(StrEnum):
    NONE = "NONE"
    EXTERNAL_KEY = "EXTERNAL_KEY"
    INHERENT = "INHERENT"


class ToolExecutionContext(BaseModel):
    model_config = {"frozen": True}
    idempotency_key: str = Field(min_length=1)


class ToolMetadata(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    side_effect_free: bool = False
    idempotency_mode: IdempotencyMode = IdempotencyMode.NONE

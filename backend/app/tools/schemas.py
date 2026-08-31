from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    content: str


class ToolExecutionResult(BaseModel):
    tool_call_id: str
    tool_name: str
    content: str


class ToolMetadata(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]

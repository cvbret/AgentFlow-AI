from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None

    @model_validator(mode="after")
    def validate_tool_call_id(self) -> "ChatMessage":
        if self.role == "tool" and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        if self.role != "tool" and self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for tool messages")
        return self


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_content_or_tool_calls(self) -> "LLMResponse":
        if self.content is None and not self.tool_calls:
            raise ValueError("LLMResponse requires content or tool_calls")
        return self

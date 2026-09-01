from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ToolCall(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, Any]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_message_shape(self) -> "ChatMessage":
        if self.role == "tool":
            if not self.tool_call_id:
                raise ValueError("tool messages require tool_call_id")
            if self.content is None:
                raise ValueError("tool messages require content")
            if self.tool_calls:
                raise ValueError("tool messages cannot contain tool_calls")
            return self

        if self.tool_call_id is not None:
            raise ValueError("tool_call_id is only valid for tool messages")
        if self.role != "assistant" and self.tool_calls:
            raise ValueError("tool_calls are only valid for assistant messages")
        if self.content is None and not self.tool_calls:
            raise ValueError(
                "messages require content unless assistant messages contain tool_calls"
            )
        return self


class LLMResponse(BaseModel):
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_content_or_tool_calls(self) -> "LLMResponse":
        if self.content is None and not self.tool_calls:
            raise ValueError("LLMResponse requires content or tool_calls")
        return self

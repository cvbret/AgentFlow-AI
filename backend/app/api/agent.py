from collections.abc import Callable

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.agents.runtime import AgentMaxStepsExceededError, AgentRuntime
from app.api.dependencies import get_agent_runtime_provider
from app.llm.client import (
    ConfigurationError,
    InvalidLLMResponseError,
    LLMProviderError,
)
from app.llm.schemas import ChatMessage
from app.tools.exceptions import (
    ToolExecutionError,
    ToolInputValidationError,
    ToolNotFoundError,
)


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class AgentRunResponse(BaseModel):
    answer: str


_ERROR_RESPONSES: dict[type[Exception], tuple[int, str]] = {
    ConfigurationError: (500, "Agent configuration is unavailable."),
    LLMProviderError: (502, "LLM provider request failed."),
    InvalidLLMResponseError: (502, "LLM provider returned an invalid response."),
    AgentMaxStepsExceededError: (
        500,
        "Agent execution exceeded the maximum step limit.",
    ),
    ToolNotFoundError: (500, "Agent tool execution failed."),
    ToolInputValidationError: (500, "Agent tool execution failed."),
    ToolExecutionError: (500, "Agent tool execution failed."),
}

AGENT_DOMAIN_ERRORS = tuple(_ERROR_RESPONSES)


def agent_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    status_code, detail = _ERROR_RESPONSES[type(exc)]
    return JSONResponse(status_code=status_code, content={"detail": detail})


router = APIRouter()


@router.post("/agent/run", response_model=AgentRunResponse)
def run_agent(
    request: AgentRunRequest,
    runtime_provider: Callable[[], AgentRuntime] = Depends(
        get_agent_runtime_provider
    ),
) -> AgentRunResponse:
    result = runtime_provider().run(
        [ChatMessage(role="user", content=request.message)]
    )
    return AgentRunResponse(answer=result.content)

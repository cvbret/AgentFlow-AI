"""Agent definitions and backward-compatible lazy Runtime exports."""

from typing import TYPE_CHECKING

from app.agents.exceptions import (
    AgentDefinitionError,
    AgentError,
    AgentMaxStepsExceededError,
    AgentNotFoundError,
    AgentToolPermissionError,
    DuplicateAgentError,
)
from app.agents.models import Agent
from app.agents.policy import AgentToolPolicy
from app.agents.registry import AgentRegistry

if TYPE_CHECKING:
    from app.agents.runtime import AgentResult, AgentRuntime

__all__ = [
    "Agent",
    "AgentRegistry",
    "AgentToolPolicy",
    "AgentDefinitionError",
    "DuplicateAgentError",
    "AgentNotFoundError",
    "AgentToolPermissionError",
    "AgentError",
    "AgentMaxStepsExceededError",
    "AgentResult",
    "AgentRuntime",
]


def __getattr__(name: str):
    if name in {"AgentResult", "AgentRuntime"}:
        from app.agents.runtime import AgentResult, AgentRuntime

        return {"AgentResult": AgentResult, "AgentRuntime": AgentRuntime}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

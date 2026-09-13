"""Trusted invocation identity; enforcement belongs to Tool boundaries, not graphs.

Unscoped legacy callers retain their pre-Agent API contract. Agent entry points
must establish this context from trusted Agent definitions, never model payloads.
Context is invocation-local transport. AgentRuntime persists provenance and
restores it before workflow continuation; this module is not authentication.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from app.agents.models import Agent
from app.agents.policy import AgentToolPolicy
from app.agents.exceptions import AgentToolPermissionError
from app.observability import emit
from app.tools.exceptions import ToolPermissionDenied

_agent: ContextVar[Agent | None] = ContextVar("tool_permission_agent", default=None)


@contextmanager
def tool_permission_context(agent: Agent):
    if not isinstance(agent, Agent):
        raise TypeError("Permission context requires a trusted Agent")
    token = _agent.set(agent)
    try:
        yield
    finally:
        _agent.reset(token)


def current_tool_agent() -> Agent | None:
    return _agent.get()


def ensure_tool_permission(tool_name: str) -> None:
    agent = _agent.get()
    if agent is None:
        return  # Existing non-Agent Runtime/API compatibility; not an Agent grant.
    try:
        AgentToolPolicy().ensure_allowed(agent, tool_name)
    except AgentToolPermissionError:
        emit("tool.permission.denied", component="execution", outcome="failed",
             attributes={"tool_name": tool_name, "exception_type": "ToolPermissionDenied"})
        raise ToolPermissionDenied(agent.name, tool_name) from None

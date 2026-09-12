"""Explicit in-memory Agent discovery, without execution dependencies."""

from app.agents.exceptions import (
    AgentDefinitionError,
    AgentNotFoundError,
    DuplicateAgentError,
)
from app.agents.models import Agent


class AgentRegistry:
    """Register definitions by exact name during application composition."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register(self, agent: Agent) -> None:
        if not isinstance(agent, Agent):
            raise AgentDefinitionError("Only Agent instances can be registered")
        if agent.name in self._agents:
            raise DuplicateAgentError(f"Agent already registered: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> Agent:
        try:
            return self._agents[name]
        except KeyError as exc:
            raise AgentNotFoundError(f"Agent not found: {name}") from exc

    def list(self) -> list[Agent]:
        return list(self._agents.values())

"""First-layer role grants; not a replacement for Tool Runtime safety."""

from app.agents.exceptions import AgentToolPermissionError
from app.agents.models import Agent


class AgentToolPolicy:
    """Check exact tool-name membership only.

    An allow result is not execution authorization: registry resolution, safety
    policy, HITL and Ledger checks remain the existing Tool Runtime's concern.
    This policy is not wired into execution by the abstraction foundation.
    """

    @staticmethod
    def is_allowed(agent: Agent, tool_name: str) -> bool:
        return tool_name in agent.allowed_tools

    def ensure_allowed(self, agent: Agent, tool_name: str) -> None:
        if not self.is_allowed(agent, tool_name):
            raise AgentToolPermissionError(
                f"Agent '{agent.name}' is not allowed to request tool '{tool_name}'"
            )

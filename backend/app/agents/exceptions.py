class AgentError(RuntimeError):
    """Base error for the Agent runtime."""


class AgentMaxStepsExceededError(AgentError):
    """Raised when the Agent does not produce a final answer in time."""


class AgentDefinitionError(ValueError):
    """Invalid Agent registration or definition operation."""


class DuplicateAgentError(AgentDefinitionError):
    """An Agent with this exact name is already registered."""


class AgentNotFoundError(AgentDefinitionError):
    """No Agent is registered under the requested name."""


class AgentToolPermissionError(PermissionError):
    """The Agent's first-layer tool grant does not allow the request."""

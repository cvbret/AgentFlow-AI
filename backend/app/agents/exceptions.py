class AgentError(RuntimeError):
    """Base error for the Agent runtime."""


class AgentMaxStepsExceededError(AgentError):
    """Raised when the Agent does not produce a final answer in time."""

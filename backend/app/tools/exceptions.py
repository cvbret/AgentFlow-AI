class ToolError(RuntimeError):
    """Base error for the Tool domain."""


class ToolInputValidationError(ToolError):
    """Raised when Tool input does not satisfy its Pydantic schema."""


class ToolExecutionError(ToolError):
    """Raised when a Tool cannot execute a validated input."""


class DuplicateToolError(ToolError):
    """Raised when a Tool name is already registered."""


class ToolNotFoundError(ToolError):
    """Raised when a requested Tool name is not registered."""


class ToolExecutionOutcomeUnknown(ToolExecutionError):
    """External effect may have occurred; automatic replay is prohibited."""


class ToolExecutionFailedWithoutEffect(ToolExecutionError):
    """Explicit Tool contract: operation failed with no external effect."""

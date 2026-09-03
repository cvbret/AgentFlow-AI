class TaskError(RuntimeError):
    """Base error for the Task domain."""


class InvalidTaskStateTransitionError(TaskError):
    """Raised when a Task lifecycle transition is not allowed."""

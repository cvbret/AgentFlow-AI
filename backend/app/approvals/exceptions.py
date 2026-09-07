class ApprovalError(RuntimeError):
    """Base error for the Approval domain."""


class InvalidApprovalStateTransitionError(ApprovalError):
    """Raised when an Approval decision transition is not allowed."""

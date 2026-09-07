"""Approval domain model for protected ToolCall decisions."""

from app.approvals.exceptions import (
    ApprovalError,
    InvalidApprovalStateTransitionError,
)
from app.approvals.models import Approval, ApprovalStatus

__all__ = [
    "Approval",
    "ApprovalError",
    "ApprovalStatus",
    "InvalidApprovalStateTransitionError",
]

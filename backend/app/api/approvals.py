from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.dependencies import get_approval_decision_service
from app.approvals.models import Approval
from app.approvals.service import (
    ApprovalDecisionService,
    ApprovalNotFoundError,
    ApprovalDecisionConflictError,
    ApprovalTaskContextError,
)


class ApprovalDecisionResponse(BaseModel):
    approval_id: UUID
    task_id: UUID
    status: Literal["approved", "rejected"]
    decided_at: datetime

    @classmethod
    def from_domain(cls, approval: Approval) -> "ApprovalDecisionResponse":
        return cls(
            approval_id=approval.id,
            task_id=approval.task_id,
            status=approval.status.value.lower(),
            decided_at=approval.decided_at,
        )


APPROVAL_ERRORS = (ApprovalNotFoundError, ApprovalDecisionConflictError, ApprovalTaskContextError)


def approval_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request
    if isinstance(exc, ApprovalNotFoundError):
        return JSONResponse(status_code=404, content={"detail": "Approval not found."})
    if isinstance(exc, ApprovalTaskContextError):
        return JSONResponse(status_code=409, content={"detail": "Approval Task is not waiting for approval."})
    return JSONResponse(status_code=409, content={"detail": "Approval decision conflict."})


router = APIRouter()


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalDecisionResponse)
def approve(approval_id: UUID, service: ApprovalDecisionService = Depends(get_approval_decision_service)) -> ApprovalDecisionResponse:
    return ApprovalDecisionResponse.from_domain(service.decide(approval_id, "approve"))


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalDecisionResponse)
def reject(approval_id: UUID, service: ApprovalDecisionService = Depends(get_approval_decision_service)) -> ApprovalDecisionResponse:
    return ApprovalDecisionResponse.from_domain(service.decide(approval_id, "reject"))

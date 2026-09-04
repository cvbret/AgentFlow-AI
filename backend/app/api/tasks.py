from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.tasks.models import Task
from app.tasks.repository import TaskRepository
from app.api.dependencies import get_task_repository


class TaskQueryResponse(BaseModel):
    id: UUID
    status: str
    input: str
    result: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, task: Task) -> "TaskQueryResponse":
        return cls(
            id=task.id,
            status=task.status.value.lower(),
            input=task.input,
            result=task.result,
            error=task.error,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )


router = APIRouter()


@router.get("/tasks/{task_id}", response_model=TaskQueryResponse)
def get_task(
    task_id: UUID,
    repository: TaskRepository = Depends(get_task_repository),
) -> TaskQueryResponse:
    task = repository.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return TaskQueryResponse.from_domain(task)

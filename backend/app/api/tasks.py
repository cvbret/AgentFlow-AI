from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.tasks.models import Task, TaskStatus
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


class TaskListResponse(BaseModel):
    items: list[TaskQueryResponse]
    limit: int
    offset: int


TaskStatusQuery = Literal["pending", "running", "succeeded", "failed"]


router = APIRouter()


@router.get("/tasks", response_model=TaskListResponse)
def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: TaskStatusQuery = Query(default=None),
    repository: TaskRepository = Depends(get_task_repository),
) -> TaskListResponse:
    if status is None:
        tasks = repository.list(limit=limit, offset=offset)
    else:
        tasks = repository.list(
            limit=limit,
            offset=offset,
            status=TaskStatus(status.upper()),
        )
    return TaskListResponse(
        items=[TaskQueryResponse.from_domain(task) for task in tasks],
        limit=limit,
        offset=offset,
    )


@router.get("/tasks/{task_id}", response_model=TaskQueryResponse)
def get_task(
    task_id: UUID,
    repository: TaskRepository = Depends(get_task_repository),
) -> TaskQueryResponse:
    task = repository.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return TaskQueryResponse.from_domain(task)

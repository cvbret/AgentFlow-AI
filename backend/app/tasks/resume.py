from collections.abc import Callable
from uuid import UUID

from app.agents.runtime import AgentRuntime

from sqlalchemy.orm import Session

from app.approved_execution import ResumeAuthorizationError
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.pause_persistence import HITLPausePersistence
from app.tasks.service import TaskExecutionService


class TaskResumeService:
    """Continue an already committed RUNNING claim outside business transactions."""
    def __init__(self, session: Session, runtime_provider: Callable[[], AgentRuntime]) -> None:
        self._session = session
        self._runtime_provider = runtime_provider

    def resume(self, task_id: UUID, approval_id: UUID) -> Task:
        repository = TaskRepository(self._session)
        task = repository.get(task_id)
        self._session.rollback()  # End the read transaction before Graph/LLM/Tool.
        if task is None or task.status is not TaskStatus.RUNNING:
            raise ResumeAuthorizationError("Continuation requires a RUNNING Task")
        service = TaskExecutionService(repository, self._runtime_provider, HITLPausePersistence(self._session))
        return service.continue_running(task, lambda: self._runtime_provider().resume(
            task_id=task_id, approval_id=approval_id))

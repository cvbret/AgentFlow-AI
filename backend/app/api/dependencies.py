from collections.abc import Callable, Generator
from threading import Lock

from fastapi import Depends
from sqlalchemy.orm import Session

from app.agents.runtime import AgentRuntime
from app.approvals.repository import ApprovalRepository
from app.approvals.service import ApprovalDecisionService
from app.approvals.rejection_persistence import ApprovalRejectionPersistence
from app.tasks.pause_persistence import HITLPausePersistence
from app.core.config import get_settings
from app.db.session import get_session_factory
from app.llm.client import LLMClient
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskExecutionService
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


_agent_runtime: AgentRuntime | None = None
_agent_runtime_lock = Lock()


def build_agent_runtime() -> AgentRuntime:
    settings = get_settings()
    llm_client = LLMClient(settings=settings)
    tool_registry = ToolRegistry()
    tool_registry.register(CalculatorTool())
    return AgentRuntime(llm_client=llm_client, tool_registry=tool_registry)


def get_agent_runtime() -> AgentRuntime:
    global _agent_runtime
    runtime = _agent_runtime
    if runtime is not None:
        return runtime

    with _agent_runtime_lock:
        runtime = _agent_runtime
        if runtime is None:
            runtime = build_agent_runtime()
            _agent_runtime = runtime
        return runtime


def get_agent_runtime_provider() -> Callable[[], AgentRuntime]:
    return get_agent_runtime


def get_db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_task_repository(
    session: Session = Depends(get_db_session),
) -> TaskRepository:
    return TaskRepository(session)


def get_task_execution_service(
    session: Session = Depends(get_db_session),
    repository: TaskRepository = Depends(get_task_repository),
    runtime_provider: Callable[[], AgentRuntime] = Depends(
        get_agent_runtime_provider
    ),
) -> TaskExecutionService:
    return TaskExecutionService(
        repository=repository,
        runtime_provider=runtime_provider,
        pause_persistence=HITLPausePersistence(session),
    )


def close_agent_runtime() -> None:
    global _agent_runtime
    with _agent_runtime_lock:
        runtime = _agent_runtime
        _agent_runtime = None
        if runtime is not None:
            runtime.close()


def get_approval_decision_service(
    session: Session = Depends(get_db_session),
) -> ApprovalDecisionService:
    return ApprovalDecisionService(ApprovalRepository(session), TaskRepository(session), ApprovalRejectionPersistence(session))

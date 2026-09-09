import os
from collections.abc import Iterator
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import delete, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.approvals import ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.db.models import ApprovalRecord, TaskRecord
from app.llm.schemas import ToolCall
from app.protected_execution import ApprovalRequired, ProtectedToolExecutionService
from app.tasks import Task
from app.tasks.repository import TaskRepository
from app.tasks.pause_persistence import HITLPausePersistence
from app.tools.base import Tool
from app.tools.exceptions import ToolNotFoundError
from app.tools.implementations.calculator import CalculatorInput, CalculatorTool
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolResult


class RecordingUnannotatedTool(Tool):
    name = "recording_unannotated"
    description = "A test tool without an explicit safety annotation."
    input_schema = CalculatorInput

    def __init__(self) -> None:
        super().__init__()
        self.execution_count = 0

    def _execute(self, input_data) -> ToolResult:
        self.execution_count += 1
        return ToolResult(content="executed")


class RecordingSideEffectfulTool(RecordingUnannotatedTool):
    name = "recording_side_effectful"
    side_effect_free = False


def make_tool_call(
    *,
    name: str,
    call_id: str = "call_123",
) -> ToolCall:
    return ToolCall(
        id=call_id,
        name=name,
        arguments={"operation": "add", "a": 2, "b": 3},
    )


@pytest.fixture
def no_standalone_commit():
    with patch.object(ApprovalRepository, "create") as create:
        yield
    create.assert_not_called()


def test_safe_tool_executes_without_creating_approval(no_standalone_commit) -> None:
    registry = ToolRegistry()
    tool = CalculatorTool()
    registry.register(tool)
    service = ProtectedToolExecutionService(registry)

    tool_call = make_tool_call(name="calculator")
    with patch.object(tool, "execute", wraps=tool.execute) as execute:
        result = service.execute(task_id=uuid4(), tool_call=tool_call)

    execute.assert_called_once_with(tool_call.arguments)

    assert result.content == "5.0"


def test_unknown_tool_raises_without_creating_approval(no_standalone_commit) -> None:
    service = ProtectedToolExecutionService(ToolRegistry())

    with pytest.raises(ToolNotFoundError):
        service.execute(
            task_id=uuid4(),
            tool_call=make_tool_call(name="unknown_tool"),
        )



@pytest.mark.parametrize("tool_type", [RecordingUnannotatedTool, RecordingSideEffectfulTool])
def test_protected_tool_creates_pending_approval_and_never_executes(
    tool_type: type[RecordingUnannotatedTool],
    no_standalone_commit,
) -> None:
    tool = tool_type()
    registry = ToolRegistry()
    registry.register(tool)
    task_id = uuid4()
    tool_call = make_tool_call(name=tool.name)
    service = ProtectedToolExecutionService(registry)

    with pytest.raises(ApprovalRequired) as raised:
        service.execute(task_id=task_id, tool_call=tool_call)

    approval = raised.value.approval
    assert approval.status is ApprovalStatus.PENDING
    assert approval.decided_at is None
    assert approval.task_id == task_id
    assert approval.tool_call_id == tool_call.id
    assert approval.tool_name == tool.name
    assert approval.arguments == tool_call.arguments
    assert raised.value.approval_id == approval.id
    assert raised.value.task_id == task_id
    assert raised.value.tool_call_id == tool_call.id
    assert raised.value.tool_name == tool.name
    assert tool.execution_count == 0


@pytest.fixture(scope="session")
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    return value


@pytest.fixture(scope="session")
def engine(database_url: str) -> Iterator[Engine]:
    from sqlalchemy import create_engine

    test_engine = create_engine(database_url)
    with test_engine.connect() as connection:
        inspector = inspect(connection)
        assert inspector.has_table("tasks")
        assert inspector.has_table("approvals")
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as db_session:
        yield db_session
        db_session.rollback()
        db_session.execute(delete(ApprovalRecord))
        db_session.execute(delete(TaskRecord))
        db_session.commit()


def test_protected_execution_persists_pending_approval_on_postgresql(
    session: Session,
) -> None:
    task = Task(input="protected execution")
    task.start()
    TaskRepository(session).save(task)
    tool = RecordingSideEffectfulTool()
    registry = ToolRegistry()
    registry.register(tool)
    service = ProtectedToolExecutionService(registry)
    tool_call = make_tool_call(name=tool.name, call_id="call_postgres")

    with pytest.raises(ApprovalRequired) as raised:
        service.execute(task_id=task.id, tool_call=tool_call)

    # The signal itself is unpersisted; only atomic pause makes it durable.
    with Session(session.get_bind()) as read_session:
        assert ApprovalRepository(read_session).get_by_id(raised.value.approval_id) is None
    expected = Task.restore(**task.model_dump())
    task.mark_waiting_approval()
    HITLPausePersistence(session).save(task, raised.value.approval, expected=expected)

    # A separate Session must see the committed Approval after atomic pause.
    with Session(session.get_bind()) as read_session:
        loaded = ApprovalRepository(read_session).get_by_id(raised.value.approval_id)

    assert loaded is not None
    assert loaded.id == raised.value.approval_id
    assert loaded.task_id == raised.value.task_id
    assert loaded.tool_call_id == raised.value.tool_call_id
    assert loaded.tool_name == raised.value.tool_name
    assert loaded.status is ApprovalStatus.PENDING
    assert loaded.decided_at is None
    assert loaded.task_id == task.id
    assert loaded.tool_call_id == tool_call.id
    assert loaded.tool_name == tool.name
    assert loaded.arguments == tool_call.arguments
    assert loaded.created_at.tzinfo is not None
    assert loaded.created_at.utcoffset() == timedelta(0)
    assert tool.execution_count == 0

import os
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select, event, text
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from sqlalchemy.orm import Session

from app.agents.runtime import AgentRuntime
from app.api.dependencies import get_agent_runtime_provider, get_db_session
from app.approvals import ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.db.models import ApprovalRecord, TaskRecord
from app.llm.schemas import ChatMessage, LLMResponse, ToolCall
from app.main import app
from app.protected_execution import ApprovalRequired
from app.tasks import Task, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.pause_persistence import HITLPausePersistence
from app.tasks.service import TaskExecutionService
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


class ProtectedCalculator(CalculatorTool):
    side_effect_free = False


def make_runtime(*, safe=False):
    tool = CalculatorTool() if safe else ProtectedCalculator()
    registry = ToolRegistry()
    registry.register(tool)
    call = ToolCall(id="pause_call", name=tool.name, arguments={"operation": "add", "a": 2, "b": 3})
    llm = Mock()
    llm.chat.side_effect = [LLMResponse(tool_calls=[call, call] if not safe else [call]), LLMResponse(content="5")]
    return AgentRuntime(llm, registry), tool, llm, call


def recording_tasks():
    repository = Mock(spec=TaskRepository)
    snapshots = []
    repository.save.side_effect = lambda task: snapshots.append(task.model_copy(deep=True))
    repository.save_failed_if_running.side_effect = lambda task, expected: repository.save.side_effect(task)
    return repository, snapshots


def test_runtime_propagates_signal_and_stops_before_next_tool_or_llm():
    runtime, tool, llm, call = make_runtime()
    task_id = uuid4()
    with patch.object(tool, "execute", wraps=tool.execute) as execute:
        with pytest.raises(ApprovalRequired) as raised:
            runtime.run([ChatMessage(role="user", content="pause")], task_id=task_id)
    execute.assert_not_called()
    approval = raised.value.approval
    assert raised.value.approval_id == approval.id
    assert raised.value.task_id == approval.task_id == task_id
    assert raised.value.tool_call_id == approval.tool_call_id == call.id
    assert raised.value.tool_name == approval.tool_name == call.name
    assert llm.chat.call_count == 1


def test_service_returns_waiting_only_after_atomic_save():
    runtime, _, _, _ = make_runtime()
    tasks, snapshots = recording_tasks()
    pause = Mock(spec=HITLPausePersistence)
    def save(waiting, approval, *, expected):
        assert expected.model_dump() == snapshots[-1].model_dump()
        assert snapshots[-1].status is TaskStatus.RUNNING
        assert approval.task_id == waiting.id == snapshots[-1].id
        assert waiting.status is TaskStatus.WAITING_APPROVAL
    pause.save.side_effect = save
    task = TaskExecutionService(tasks, lambda: runtime, pause).execute("pause")
    pause.save.assert_called_once()
    assert [t.status for t in snapshots] == [TaskStatus.PENDING, TaskStatus.RUNNING]
    assert task.status is TaskStatus.WAITING_APPROVAL
    assert task.result is None and task.error is None


@pytest.mark.parametrize("error", [SQLAlchemyError("atomic save failed"), RuntimeError("unexpected secret")])
def test_pause_failure_uses_original_running_task_for_failed_transition(error):
    runtime, tool, llm, _ = make_runtime()
    tasks, snapshots = recording_tasks()
    pause = Mock(spec=HITLPausePersistence)
    pause.save.side_effect = error
    with patch.object(tool, "execute", wraps=tool.execute) as execute:
        with pytest.raises(type(error)) as raised:
            TaskExecutionService(tasks, lambda: runtime, pause).execute("fail")
    assert raised.value is error
    execute.assert_not_called()
    assert [t.status for t in snapshots] == [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.FAILED]
    assert snapshots[-1].error == "Agent execution failed."
    assert llm.chat.call_count == 1


@pytest.fixture
def engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    engine = create_engine(url)
    try:
        yield engine
    finally:
        with Session(engine) as session:
            session.execute(delete(ApprovalRecord))
            session.execute(delete(TaskRecord))
            session.commit()
        engine.dispose()


@pytest.mark.parametrize("safe", [False, True])
def test_real_api_runtime_task_approval_round_trip_and_filter(engine, safe):
    runtime, tool, llm, call = make_runtime(safe=safe)
    def db_session():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db_session] = db_session
    app.dependency_overrides[get_agent_runtime_provider] = lambda: lambda: runtime
    expected = "succeeded" if safe else "waiting_approval"
    try:
        with TestClient(app) as client, patch.object(tool, "execute", wraps=tool.execute) as execute:
            response = client.post("/api/agent/run", json={"message": "integration pause"})
            assert response.status_code == 200
            payload = response.json()
            task_id = UUID(payload["task_id"])
            assert payload == {"task_id": str(task_id), "status": expected, "answer": "5" if safe else None}
            query = client.get(f"/api/tasks/{task_id}")
            assert query.status_code == 200
            assert query.json()["status"] == expected
            assert query.json()["error"] is None
            filtered = client.get(f"/api/tasks?status={expected}")
            assert filtered.status_code == 200
            assert [t["id"] for t in filtered.json()["items"]] == [str(task_id)]
            other = "waiting_approval" if safe else "succeeded"
            assert client.get(f"/api/tasks?status={other}").json()["items"] == []
            if safe:
                execute.assert_called_once_with(call.arguments)
                assert llm.chat.call_count == 2
            else:
                execute.assert_not_called()
                assert llm.chat.call_count == 1
        with Session(engine) as read_session:
            task = TaskRepository(read_session).get(task_id)
            assert task.status is TaskStatus(expected.upper())
            assert task.error is None
            records = read_session.scalars(select(ApprovalRecord).where(ApprovalRecord.task_id == task_id)).all()
            if safe:
                assert records == []
            else:
                assert len(records) == 1
                approval = ApprovalRepository(read_session).get_by_id(records[0].id)
                assert approval.status is ApprovalStatus.PENDING
                assert approval.task_id == task.id
                assert approval.tool_call_id == call.id
                assert approval.tool_name == call.name
                assert approval.arguments == call.arguments
    finally:
        app.dependency_overrides.clear()




@pytest.fixture(params=["approval_insert", "waiting_update", "commit"])
def postgres_pause_failure(engine, request):
    failure = request.param
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE FUNCTION task023_fail_pause() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'task023 injected pause failure'; END;
            $$
        """))
        if failure == "waiting_update":
            ddl = """CREATE TRIGGER task023_pause_failure BEFORE UPDATE ON tasks
                FOR EACH ROW WHEN (NEW.status = 'WAITING_APPROVAL')
                EXECUTE FUNCTION task023_fail_pause()"""
            table = "tasks"
        elif failure == "approval_insert":
            ddl = """CREATE TRIGGER task023_pause_failure BEFORE INSERT ON approvals
                FOR EACH ROW EXECUTE FUNCTION task023_fail_pause()"""
            table = "approvals"
        else:
            ddl = """CREATE CONSTRAINT TRIGGER task023_pause_failure AFTER INSERT ON approvals
                DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
                EXECUTE FUNCTION task023_fail_pause()"""
            table = "approvals"
        connection.execute(text(ddl))
    try:
        yield failure
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP TRIGGER task023_pause_failure ON {table}"))
            connection.execute(text("DROP FUNCTION task023_fail_pause()"))


def assert_failed_without_approval(engine):
    with Session(engine) as read_session:
        records = read_session.scalars(select(TaskRecord)).all()
        assert len(records) == 1
        task = TaskRepository(read_session).get(records[0].id)
        assert task.status is TaskStatus.FAILED
        assert task.result is None
        assert task.error == "Agent execution failed."
        assert read_session.scalars(select(ApprovalRecord)).all() == []


def test_postgresql_pause_failure_rolls_back_both_writes(engine, postgres_pause_failure):
    runtime, tool, llm, _ = make_runtime()
    completed_sql = []
    def record_sql(connection, cursor, statement, parameters, context, executemany):
        completed_sql.append(statement)
    event.listen(engine, "after_cursor_execute", record_sql)
    try:
        with Session(engine) as session:
            tasks = TaskRepository(session)
            snapshots = []
            original_save = tasks.save
            def save(task):
                snapshots.append(task.model_copy(deep=True))
                return original_save(task)
            original_fail = tasks.save_failed_if_running
            def fail(task, expected):
                snapshots.append(task.model_copy(deep=True))
                updated = original_fail(task, expected)
                assert updated is True
                return updated
            with patch.object(tasks, "save", side_effect=save), patch.object(tasks, "save_failed_if_running", side_effect=fail), patch.object(tool, "execute", wraps=tool.execute) as execute:
                with pytest.raises(SQLAlchemyError, match="task023 injected pause failure"):
                    TaskExecutionService(tasks, lambda: runtime, HITLPausePersistence(session)).execute("failure injection")
            execute.assert_not_called()
            assert not session.in_transaction()
            assert [t.status for t in snapshots] == [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.FAILED]
        if postgres_pause_failure in ("waiting_update", "commit"):
            assert any(sql.startswith("INSERT INTO approvals") for sql in completed_sql)
        if postgres_pause_failure == "commit":
            # UPDATE completed successfully; only the deferred trigger at COMMIT fails.
            assert sum(sql.startswith("UPDATE tasks") for sql in completed_sql) == 3
        assert llm.chat.call_count == 1
        assert_failed_without_approval(engine)
    finally:
        event.remove(engine, "after_cursor_execute", record_sql)


def test_api_atomic_failure_never_returns_waiting_success(engine, postgres_pause_failure):
    runtime, tool, _, _ = make_runtime()
    def db_session():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db_session] = db_session
    app.dependency_overrides[get_agent_runtime_provider] = lambda: lambda: runtime
    try:
        with TestClient(app, raise_server_exceptions=False) as client, patch.object(tool, "execute", wraps=tool.execute) as execute:
            response = client.post("/api/agent/run", json={"message": "atomic failure"})
        assert response.status_code == 500
        assert "waiting_approval" not in response.text
        execute.assert_not_called()
        assert_failed_without_approval(engine)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("safe", [False, True])
def test_pause_one_commit_and_no_transaction_across_llm(engine, safe):
    runtime, tool, llm, call = make_runtime(safe=safe)
    with Session(engine) as session:
        responses = iter([LLMResponse(tool_calls=[call]), LLMResponse(content="5")])
        def chat(**kwargs):
            assert not session.in_transaction()
            return next(responses)
        llm.chat.side_effect = chat
        commits = []
        def before_commit(current):
            # The first two commits persist PENDING and RUNNING. The third is
            # either success or the ONLY pause commit, after both SQL writes.
            commits.append(True)
            if len(commits) == 3 and not safe:
                assert current.scalar(select(TaskRecord.status)) == "WAITING_APPROVAL"
                assert current.scalar(select(ApprovalRecord.status)) == "PENDING"
                with Session(engine) as observer:
                    assert observer.scalar(select(TaskRecord.status)) == "RUNNING"
                    assert observer.scalar(select(ApprovalRecord.id)) is None
        event.listen(session, "before_commit", before_commit)
        pause = HITLPausePersistence(session)
        with patch.object(pause, "save", wraps=pause.save) as pause_save, patch.object(tool, "execute", wraps=tool.execute) as execute:
            task = TaskExecutionService(TaskRepository(session), lambda: runtime, pause).execute("atomic success")
        assert len(commits) == 3
        assert not session.in_transaction()
        if safe:
            pause_save.assert_not_called()
            execute.assert_called_once_with(call.arguments)
        else:
            pause_save.assert_called_once()
            execute.assert_not_called()
    with Session(engine) as observer:
        loaded = TaskRepository(observer).get(task.id)
        assert loaded.status is (TaskStatus.SUCCEEDED if safe else TaskStatus.WAITING_APPROVAL)
        approval = observer.scalar(select(ApprovalRecord))
        if safe:
            assert approval is None
        else:
            assert approval.task_id == task.id
            assert approval.status == "PENDING"


def test_staging_methods_do_not_commit_and_rollback_together(engine):
    from app.approvals.models import Approval
    task = Task(input="staging")
    task.start()
    with Session(engine) as session:
        TaskRepository(session).save(task)
        task.mark_waiting_approval()
        approval = Approval(task_id=task.id, tool_call_id="stage", tool_name="calculator", arguments={})
        with patch.object(session, "commit", wraps=session.commit) as commit:
            ApprovalRepository(session).stage_create(approval)
            session.flush()
            staged = TaskRepository(session).stage_save(task)
            session.flush()
            assert staged.status is TaskStatus.WAITING_APPROVAL
            commit.assert_not_called()
            with Session(engine) as observer:
                assert TaskRepository(observer).get(task.id).status is TaskStatus.RUNNING
                assert ApprovalRepository(observer).get_by_id(approval.id) is None
            session.rollback()
    with Session(engine) as observer:
        assert TaskRepository(observer).get(task.id).status is TaskStatus.RUNNING
        assert ApprovalRepository(observer).get_by_id(approval.id) is None


def test_rollback_failure_preserves_original_error_and_never_executes():
    runtime, tool, _, _ = make_runtime()
    tasks, snapshots = recording_tasks()
    session = Mock(spec=Session)
    session.in_transaction.return_value = False
    original = SQLAlchemyError("stage failure")
    rollback = SQLAlchemyError("rollback failure")
    session.add.side_effect = original
    session.rollback.side_effect = rollback
    with patch.object(tool, "execute", wraps=tool.execute) as execute:
        with pytest.raises(SQLAlchemyError) as raised:
            TaskExecutionService(tasks, lambda: runtime, HITLPausePersistence(session)).execute("rollback failure")
    assert raised.value is original
    assert raised.value.__cause__ is rollback
    session.invalidate.assert_called_once()
    session.commit.assert_not_called()
    execute.assert_not_called()
    assert snapshots[-1].status is TaskStatus.FAILED


def test_failed_state_save_is_best_effort_and_preserves_pause_error():
    runtime, tool, _, _ = make_runtime()
    tasks = Mock(spec=TaskRepository)
    secondary = SQLAlchemyError("FAILED save failed")
    tasks.save.side_effect = [None, None]
    tasks.save_failed_if_running.side_effect = secondary
    pause = Mock(spec=HITLPausePersistence)
    original = SQLAlchemyError("pause failed")
    pause.save.side_effect = original
    with patch.object(tool, "execute", wraps=tool.execute) as execute:
        with pytest.raises(SQLAlchemyError) as raised:
            TaskExecutionService(tasks, lambda: runtime, pause).execute("failure")
    assert raised.value is original
    assert raised.value.__cause__ is secondary
    assert tasks.save_failed_if_running.call_args.args[0].status is TaskStatus.FAILED
    execute.assert_not_called()


@pytest.mark.parametrize("through_api", [False, True])
def test_real_commit_acknowledgement_loss_preserves_durable_pause(engine, through_api):
    runtime, tool, _, call = make_runtime()
    error = OperationalError("COMMIT", {}, RuntimeError("acknowledgement lost"))
    outcomes = []
    with Session(engine) as session:
        commit = session.commit
        commit_count = 0
        def commit_then_lose_ack():
            nonlocal commit_count
            commit_count += 1
            commit()
            if commit_count == 3:
                # PostgreSQL has really committed both pause writes.
                raise error
        tasks = TaskRepository(session)
        conditional_save = tasks.save_failed_if_running
        def fail(candidate, expected):
            assert candidate.status is TaskStatus.FAILED
            outcome = conditional_save(candidate, expected)
            outcomes.append(outcome)
            return outcome
        service = TaskExecutionService(tasks, lambda: runtime, HITLPausePersistence(session))
        with patch.object(session, "commit", side_effect=commit_then_lose_ack), patch.object(tasks, "save_failed_if_running", side_effect=fail), patch.object(tool, "execute", wraps=tool.execute) as execute:
            if through_api:
                from app.api.dependencies import get_task_execution_service
                app.dependency_overrides[get_task_execution_service] = lambda: service
                try:
                    with TestClient(app, raise_server_exceptions=False) as client:
                        response = client.post("/api/agent/run", json={"message": "ack loss"})
                    assert response.status_code == 500
                finally:
                    app.dependency_overrides.clear()
            else:
                with pytest.raises(OperationalError) as raised:
                    service.execute("ack loss")
                assert raised.value is error
            execute.assert_not_called()
        assert outcomes == [False]
    with Session(engine) as observer:
        task = observer.scalar(select(TaskRecord))
        approval = observer.scalar(select(ApprovalRecord))
        assert task.status == "WAITING_APPROVAL"
        assert task.error is None and task.result is None
        assert approval.status == "PENDING"
        assert approval.task_id == task.id
        assert approval.tool_call_id == call.id

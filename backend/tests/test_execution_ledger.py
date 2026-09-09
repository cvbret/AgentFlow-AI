"""Durable deduplication under normal concurrency; no universal exactly-once claim."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from threading import Barrier, Event
from unittest.mock import Mock, patch
from uuid import uuid4
import os

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, func, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from test_approval_decision import engine
from app.approvals.models import Approval, ApprovalStatus
from app.approvals.repository import ApprovalRepository
from app.approved_execution import ApprovedToolExecutionService, ResumeAuthorizationError
from app.db.models import ToolExecutionRecord
from app.executions.models import ToolExecution, ExecutionStatus, canonical_arguments
from app.executions.repository import ExecutionRepository
from app.executions.exceptions import ExecutionIdentityConflict, ExecutionReplayBlocked, ExecutionPersistenceConflict
from app.llm.schemas import ToolCall, LLMResponse
from app.tasks.models import Task
from app.tasks.repository import TaskRepository
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry
from app.tools.schemas import IdempotencyMode, ToolExecutionContext, ToolResult
from app.tools.exceptions import ToolExecutionFailedWithoutEffect, ToolExecutionOutcomeUnknown, ToolExecutionError, ToolInputValidationError


def seed(engine, *, tool_name="protected", arguments=None, task_id=None, call_id="call_1"):
    call = ToolCall(id=call_id, name=tool_name,
                    arguments=arguments if arguments is not None else {"operation": "add", "a": 2, "b": 3})
    approval = Approval(task_id=task_id or uuid4(), tool_call_id=call.id, tool_name=call.name, arguments=call.arguments)
    with Session(engine) as session:
        if task_id is None:
            task = Task(id=approval.task_id, input="ledger")
            task.start()
            TaskRepository(session).save(task)
        ApprovalRepository(session).create(approval)
        approval.approve()
        ApprovalRepository(session).save(approval)
    return approval, call


def service(engine, tool, repository=None, cls=ApprovedToolExecutionService):
    registry = ToolRegistry()
    registry.register(tool)
    def load(identity):
        with Session(engine) as session:
            return ApprovalRepository(session).get_by_id(identity)
    return cls(registry, load, repository or ExecutionRepository(lambda: Session(engine)))


def execute(current, approval, call):
    return current.execute(approval_id=approval.id, task_id=approval.task_id, tool_call=call)


class RecordingTool(CalculatorTool):
    name = "protected"
    side_effect_free = False
    def __init__(self):
        super().__init__()
        self.effects = 0
    def _execute(self, data):
        self.effects += 1
        return super()._execute(data)


def test_first_execution_commits_before_effect_and_cached_replay(engine):
    approval, call = seed(engine)
    active = []
    sessions = []
    def factory():
        session = Session(engine)
        sessions.append(session)
        return session
    repository = ExecutionRepository(factory)
    class Tool(RecordingTool):
        def _execute(self, data):
            assert all(not session.in_transaction() for session in sessions)
            row = repository.get(approval.task_id, call.id)
            assert row.status is ExecutionStatus.EXECUTING
            active.append(row.id)
            return super()._execute(data)
    tool = Tool()
    initial = execute(service(engine, tool, repository), approval, call)
    stored = repository.get(approval.task_id, call.id)
    assert stored.status is ExecutionStatus.SUCCEEDED and stored.result_content == initial.content == "5.0"
    assert stored.id != approval.id and stored.idempotency_key == str(stored.id)
    assert tool.effects == 1 and active == [stored.id]
    replay = execute(service(engine, tool), approval, call)  # fresh service/repository
    assert replay == initial and tool.effects == 1
    assert repository.get(approval.task_id, call.id).idempotency_key == stored.idempotency_key
    with pytest.raises(ExecutionPersistenceConflict):
        repository.finish(stored)


def test_database_claim_race_executes_at_most_once(engine):
    approval, call = seed(engine)
    barrier, finish = Barrier(2), Event()
    class RacingRepository(ExecutionRepository):
        def get(self, task_id, tool_call_id):
            row = super().get(task_id, tool_call_id)
            barrier.wait(timeout=10)
            return row
    class Tool(RecordingTool):
        def _execute(self, data):
            assert finish.wait(timeout=10)
            return super()._execute(data)
    tool = Tool()
    def run():
        try:
            execute(service(engine, tool, RacingRepository(lambda: Session(engine))), approval, call)
            return "winner"
        except ExecutionReplayBlocked:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        try:
            done, _ = wait(futures, timeout=10, return_when=FIRST_COMPLETED)
            assert len(done) == 1 and next(iter(done)).result() == "blocked"
        finally:
            finish.set()
        assert sorted(f.result(timeout=10) for f in futures) == ["blocked", "winner"]
    assert tool.effects == 1
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ToolExecutionRecord)) == 1


@pytest.mark.parametrize("mismatch", ["approval_id", "tool_name", "arguments"])
def test_existing_execution_identity_mismatch_fails_closed(engine, mismatch):
    approval, call = seed(engine)
    tool = RecordingTool()
    execute(service(engine, tool), approval, call)
    # Authorize a different context under the same business key; ledger must still reject.
    replacement, changed = seed(engine, task_id=approval.task_id, call_id=call.id,
        tool_name="other" if mismatch == "tool_name" else call.name,
        arguments={**call.arguments, "a": 99} if mismatch == "arguments" else call.arguments)
    if mismatch != "approval_id":
        with Session(engine) as session:
            row = session.scalar(select(ToolExecutionRecord))
            row.approval_id = replacement.id  # Isolate the tool/arguments integrity check.
            session.commit()
    with pytest.raises(ExecutionIdentityConflict):
        execute(service(engine, tool), replacement, changed)
    assert tool.effects == 1


def test_canonical_arguments_ignore_dict_order(engine):
    approval, call = seed(engine)
    tool = RecordingTool()
    first = execute(service(engine, tool), approval, call)
    reordered = call.model_copy(update={"arguments": {"b": 3, "a": 2, "operation": "add"}})
    assert execute(service(engine, tool), approval, reordered) == first
    assert tool.effects == 1
    assert canonical_arguments({"a": True}) != canonical_arguments({"a": 1})


@pytest.mark.parametrize("kind", ["explicit_unknown", "generic", "known_failure"])
def test_uncertain_and_definitive_outcomes_are_not_retried(engine, kind):
    approval, call = seed(engine)
    class Tool(RecordingTool):
        def _execute(self, data):
            self.attempts = getattr(self, "attempts", 0) + 1
            if kind == "known_failure":
                raise ToolExecutionFailedWithoutEffect("rejected before operation")
            self.effects += 1
            if kind == "explicit_unknown":
                raise ToolExecutionOutcomeUnknown("remote acknowledgement lost")
            raise ToolExecutionError("transport failed after possible effect")
    tool = Tool()
    current = service(engine, tool)
    expected = ToolExecutionFailedWithoutEffect if kind == "known_failure" else ToolExecutionOutcomeUnknown
    with pytest.raises(expected):
        execute(current, approval, call)
    stored = ExecutionRepository(lambda: Session(engine)).get(approval.task_id, call.id)
    assert stored.status is (ExecutionStatus.FAILED if kind == "known_failure" else ExecutionStatus.UNKNOWN)
    assert stored.result_content is None
    assert stored.error_code == ("known_no_effect" if kind == "known_failure" else "outcome_unknown")
    with pytest.raises(ExecutionReplayBlocked if kind == "known_failure" else ToolExecutionOutcomeUnknown):
        execute(service(engine, tool), approval, call)
    assert tool.attempts == 1
    assert tool.effects == (0 if kind == "known_failure" else 1)


def test_validation_failure_has_no_claim_or_effect(engine):
    approval, call = seed(engine, arguments={"operation": "invalid", "a": 2, "b": 3})
    tool = RecordingTool()
    with pytest.raises(ToolInputValidationError):
        execute(service(engine, tool), approval, call)
    assert tool.effects == 0
    assert ExecutionRepository(lambda: Session(engine)).get(approval.task_id, call.id) is None


def test_existing_executing_blocks_even_external_key_capability(engine):
    approval, call = seed(engine)
    repository = ExecutionRepository(lambda: Session(engine))
    candidate = ToolExecution(task_id=approval.task_id, approval_id=approval.id,
        tool_call_id=call.id, tool_name=call.name, arguments=call.arguments)
    stored, won = repository.claim(candidate)
    assert won
    class Tool(RecordingTool):
        idempotency_mode = IdempotencyMode.EXTERNAL_KEY
    tool = Tool()
    with pytest.raises(ExecutionReplayBlocked, match="EXECUTING"):
        execute(service(engine, tool), approval, call)
    assert tool.effects == 0
    assert repository.get(approval.task_id, call.id).id == stored.id


def test_external_key_contract_is_stable_and_distinct(engine):
    keys, effects = [], {}
    def fake_endpoint(key):
        keys.append(key)
        return effects.setdefault(key, "external-result")
    class External(RecordingTool):
        idempotency_mode = IdempotencyMode.EXTERNAL_KEY
        def _execute_with_context(self, data, context):
            return ToolResult(content=fake_endpoint(context.idempotency_key))
        def _execute(self, data):
            raise AssertionError("external-key hook must be used")
    tool = External()
    first, call = seed(engine)
    initial = execute(service(engine, tool), first, call)
    row = ExecutionRepository(lambda: Session(engine)).get(first.task_id, call.id)
    assert keys == [row.idempotency_key]
    assert execute(service(engine, tool), first, call) == initial
    assert keys == [row.idempotency_key]  # Cached replay never calls the endpoint.
    assert ExecutionRepository(lambda: Session(engine)).get(first.task_id, call.id).idempotency_key == row.idempotency_key
    # Exercise the explicit Tool operation contract, not an automatic recovery path.
    tool.execute(call.arguments, context=ToolExecutionContext(idempotency_key=row.idempotency_key))
    assert keys == [row.idempotency_key, row.idempotency_key] and len(effects) == 1
    second, other = seed(engine)
    execute(service(engine, tool), second, other)
    assert keys[-1] != keys[0] and len(effects) == 2


@pytest.mark.parametrize("phase", ["claim", "result"])
def test_postgresql_write_failure_prevents_blind_reexecution(engine, phase):
    approval, call = seed(engine)
    tool = RecordingTool()
    operation = "INSERT" if phase == "claim" else "UPDATE"
    with engine.begin() as connection:
        connection.execute(text("CREATE FUNCTION task029_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'ledger write failed'; END; $$"))
        connection.execute(text(f"CREATE TRIGGER task029_failure BEFORE {operation} ON tool_executions FOR EACH ROW EXECUTE FUNCTION task029_fail()"))
    try:
        with pytest.raises(SQLAlchemyError, match="ledger write failed"):
            execute(service(engine, tool), approval, call)
        assert tool.effects == (0 if phase == "claim" else 1)
        row = ExecutionRepository(lambda: Session(engine)).get(approval.task_id, call.id)
        if phase == "claim":
            assert row is None
        else:
            assert row.status is ExecutionStatus.EXECUTING
            with pytest.raises(ExecutionReplayBlocked):
                execute(service(engine, tool), approval, call)
            assert tool.effects == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TRIGGER task029_failure ON tool_executions"))
            connection.execute(text("DROP FUNCTION task029_fail()"))


def test_success_cache_does_not_replace_persisted_approval(engine):
    approval, call = seed(engine)
    tool = RecordingTool()
    execute(service(engine, tool), approval, call)
    with Session(engine) as session:
        from app.db.models import ApprovalRecord
        row = session.get(ApprovalRecord, approval.id)
        row.status, row.decided_at = "PENDING", None
        session.commit()
    with pytest.raises(ResumeAuthorizationError):
        execute(service(engine, tool), approval, call)
    assert tool.effects == 1


def test_graph_replay_after_ledger_success_uses_cached_result(engine):
    from test_task_resume import runtime, start, pending, decide, call, registry
    from app.workflows.checkpoint import open_checkpointer
    from app.workflows.agent import build_agent_graph
    from langgraph.types import Command
    events = []
    agent, _ = runtime(engine, events, [LLMResponse(tool_calls=[call(2, True)])])
    task = start(engine, agent)
    approval = pending(engine, task.id)
    agent.close()
    with Session(engine) as session:
        decide(session, approval.id)
    def load(identity):
        with Session(engine) as session:
            return ApprovalRepository(session).get_by_id(identity)
    class LostProgress(ApprovedToolExecutionService):
        def execute(self, **kwargs):
            super().execute(**kwargs)
            raise RuntimeError("graph progress lost after ledger success")
    tools = registry(events)
    config = {"configurable": {"thread_id": str(task.id)}}
    with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
        graph = build_agent_graph(Mock(), tools.list(), Mock(), max_steps=5, checkpointer=saver,
            approved_execution=LostProgress(tools, load, ExecutionRepository(lambda: Session(engine))))
        with pytest.raises(RuntimeError, match="graph progress lost"):
            graph.invoke(Command(resume={"task_id": str(task.id), "approval_id": str(approval.id)}), config, durability="sync")
        assert graph.get_state(config).next == ("tool",)
    assert events == [2]
    row = ExecutionRepository(lambda: Session(engine)).get(task.id, "call_2")
    assert row.status is ExecutionStatus.SUCCEEDED
    del graph
    llm = Mock()
    llm.chat.return_value = LLMResponse(content="recovered final answer")
    with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
        graph = build_agent_graph(llm, tools.list(), Mock(), max_steps=5, checkpointer=saver,
            approved_execution=ApprovedToolExecutionService(tools, load, ExecutionRepository(lambda: Session(engine))))
        result = graph.invoke(None, config, durability="sync")  # Controlled test replay, no scanner/worker.
        assert result["final_answer"] == "recovered final answer"
    assert events == [2]  # side effect count 1 before AND after replay
    assert llm.chat.call_args.kwargs["messages"][-1].content == row.result_content


def test_domain_snapshot_stable_key_and_transitions():
    arguments = {"nested": {"b": 2, "a": 1}}
    execution = ToolExecution(task_id=uuid4(), approval_id=uuid4(), tool_call_id="call", tool_name="tool", arguments=arguments)
    arguments["nested"]["a"] = 9
    assert execution.arguments["nested"]["a"] == 1
    done = execution.finish(ExecutionStatus.SUCCEEDED, result_content="")
    assert done.idempotency_key == execution.idempotency_key == str(execution.id)
    assert ToolExecution.restore(**done.model_dump()) == done
    with pytest.raises(ValueError):
        done.finish(ExecutionStatus.UNKNOWN, error_code="uncertain")
    with pytest.raises(ValidationError):
        execution.status = ExecutionStatus.SUCCEEDED
    with pytest.raises(ValidationError):
        ToolExecution(**{**execution.model_dump(), "idempotency_key": "different"})


@pytest.mark.parametrize("mode", [IdempotencyMode.NONE, IdempotencyMode.INHERENT])
def test_tool_compatibility_and_capability(mode):
    tool = CalculatorTool()
    assert tool.metadata().idempotency_mode is IdempotencyMode.NONE
    tool.idempotency_mode = mode
    assert tool.execute({"operation": "add", "a": 1, "b": 2}).content == "3.0"
    assert tool.metadata().side_effect_free is True


def test_external_key_missing_context_fails_before_effect():
    class Tool(RecordingTool):
        idempotency_mode = IdempotencyMode.EXTERNAL_KEY
    tool = Tool()
    with pytest.raises(ToolExecutionFailedWithoutEffect):
        tool.execute({"operation": "add", "a": 1, "b": 2})
    assert tool.effects == 0


@pytest.mark.parametrize("phase", ["claim", "result"])
def test_commit_ack_loss_never_reexecutes_tool(engine, phase):
    approval, call = seed(engine)
    tool = RecordingTool()
    committed = []
    def factory():
        session = Session(engine)
        def lost_ack(current):
            committed.append(True)
            if len(committed) == (1 if phase == "claim" else 2):
                raise SQLAlchemyError("commit acknowledgement lost")
        event.listen(session, "after_commit", lost_ack)
        return session
    with pytest.raises(SQLAlchemyError, match="acknowledgement lost"):
        execute(service(engine, tool, ExecutionRepository(factory)), approval, call)
    fresh = service(engine, tool)
    repository = ExecutionRepository(lambda: Session(engine))
    stored = repository.get(approval.task_id, call.id)
    if phase == "claim":
        assert stored.status is ExecutionStatus.EXECUTING and tool.effects == 0
        with pytest.raises(ExecutionReplayBlocked):
            execute(fresh, approval, call)
        assert tool.effects == 0
    else:
        assert stored.status is ExecutionStatus.SUCCEEDED and tool.effects == 1
        assert execute(fresh, approval, call).content == stored.result_content
        assert tool.effects == 1


def test_claim_returns_existing_identity_without_new_key(engine):
    approval, call = seed(engine)
    repository = ExecutionRepository(lambda: Session(engine))
    kwargs = dict(task_id=approval.task_id, approval_id=approval.id, tool_call_id=call.id,
                  tool_name=call.name, arguments=call.arguments)
    first, won = repository.claim(ToolExecution(**kwargs))
    second, lost = repository.claim(ToolExecution(**kwargs))
    assert won and not lost
    assert first.id == second.id and first.idempotency_key == second.idempotency_key


@pytest.mark.parametrize("changes", [
    {"status": ExecutionStatus.SUCCEEDED},
    {"status": ExecutionStatus.UNKNOWN},
    {"status": ExecutionStatus.EXECUTING, "result_content": "unexpected"},
])
def test_domain_rejects_invalid_restored_state(changes):
    execution = ToolExecution(task_id=uuid4(), approval_id=uuid4(), tool_call_id="x", tool_name="t", arguments={})
    with pytest.raises(ValidationError):
        ToolExecution.restore(**{**execution.model_dump(), **changes})

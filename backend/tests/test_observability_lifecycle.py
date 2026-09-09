from contextlib import contextmanager
import json
import os
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from test_approval_decision import engine
from test_llm_client import make_settings
from test_observability import BrokenSink
from test_recovery import age, recovery, prepare, loaded, ledger
from test_task_resume import pending, decide, runtime, call, start
from app.agents.runtime import AgentRuntime, AgentResult
from app.api.dependencies import get_db_session, get_agent_runtime_provider
from app.approvals.models import Approval
from app.approvals.repository import ApprovalRepository
from app.db.models import ApprovalRecord
from app.executions.models import ExecutionStatus
from app.executions.repository import ExecutionRepository
from app.executions.exceptions import ExecutionPersistenceUncertain
from app.llm.client import LLMClient, LLMProviderError
from app.llm.schemas import ChatMessage, LLMResponse
from app.main import app
from app.observability import InMemoryObservabilitySink, use_sink, current_context, ObservabilityContext
from app.protected_execution import ApprovalRequired
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository, TaskOwnershipLost
from app.tasks.service import TaskExecutionService
from app.tasks.resume import TaskResumeService
from app.tasks.pause_persistence import HITLPausePersistence
from app.tools.base import Tool
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolResult
from app.tools.exceptions import ToolExecutionFailedWithoutEffect, ToolExecutionOutcomeUnknown
from app.workflows.checkpoint import open_checkpointer

SECRETS = {key: f"sensitive-{key}-value-8391" for key in ("password", "api_key", "token", "email", "body", "innocent")}
PROMPT = "private user prompt 1479"
RESULT = "private Tool result 2480"
ANSWER = "private model answer 3591"


class SecretInput(BaseModel):
    password: str
    api_key: str
    token: str
    email: str
    body: str
    innocent: str


class SecretTool(Tool):
    name = "protected"
    description = "Test protected operation"
    input_schema = SecretInput
    def __init__(self, failure=None):
        super().__init__()
        self.calls = 0
        self.failure = failure
    def _execute(self, data):
        self.calls += 1
        if self.failure:
            raise self.failure
        return ToolResult(content=RESULT)


@contextmanager
def secret_agent(engine, failure=None):
    responses = iter([
        {"choices": [{"message": {"content": None, "tool_calls": [{"id": "private_call", "type": "function",
            "function": {"name": "protected", "arguments": json.dumps(SECRETS)}}]}}]},
        {"choices": [{"message": {"content": ANSWER}}]},
    ])
    def respond(request):
        return httpx.Response(200, json=next(responses))
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        settings = make_settings()
        llm = LLMClient(settings, transport)
        registry = ToolRegistry()
        tool = SecretTool(failure)
        registry.register(tool)
        def load(identity):
            with Session(engine) as session:
                return ApprovalRepository(session).get_by_id(identity)
        agent = AgentRuntime(llm, registry, checkpointer_factory=lambda: open_checkpointer(os.environ["DATABASE_URL"]),
            approval_loader=load, execution_repository=ExecutionRepository(lambda: Session(engine)))
        yield agent, tool


@contextmanager
def api(engine, agent, sink):
    def sessions():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_db_session] = sessions
    app.dependency_overrides[get_agent_runtime_provider] = lambda: lambda: agent
    try:
        with use_sink(sink), TestClient(app, raise_server_exceptions=False) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def assert_private(events):
    serialized = "".join(e.to_json() for e in events)
    for value in [*SECRETS.values(), PROMPT, RESULT, ANSWER, "test-api-key"]:
        assert value not in serialized
    assert "arguments" not in serialized and "Authorization" not in serialized


@pytest.mark.parametrize("broken", [False, True])
def test_full_http_protected_lifecycle_correlation_and_privacy(engine, broken):
    sink = BrokenSink() if broken else InMemoryObservabilitySink()
    with secret_agent(engine) as (agent, tool), api(engine, agent, sink) as client:
        response_a = client.post("/api/agent/run", json={"message": PROMPT}, headers={"X-Request-ID": "untrusted-client"})
        assert response_a.status_code == 200 and response_a.json()["status"] == "waiting_approval"
        task_id = UUID(response_a.json()["task_id"])
        approval = pending(engine, task_id)
        response_b = client.post(f"/api/approvals/{approval.id}/approve")
        assert response_b.status_code == 200
        id_a, id_b = UUID(response_a.headers["X-Request-ID"]), UUID(response_b.headers["X-Request-ID"])
        assert id_a != id_b
        assert loaded(engine, task_id).status is TaskStatus.SUCCEEDED
        assert loaded(engine, task_id).result == ANSWER and tool.calls == 1
        execution = ExecutionRepository(lambda: Session(engine)).get(task_id, "private_call")
        assert execution.status is ExecutionStatus.SUCCEEDED
    assert current_context() == ObservabilityContext()
    if broken:
        assert sink.calls >= 12
        return
    events = sink.events
    assert all(e.task_id == task_id for e in events)
    assert all(e.request_id in (id_a, id_b) for e in events)
    names = [e.event_name for e in events]
    assert {"task.created", "task.state_changed", "task.completed", "workflow.paused", "workflow.resumed",
            "approval.requested", "approval.decided", "tool.execution.claimed", "tool.execution.succeeded",
            "llm.request.started", "llm.request.succeeded"} <= set(names)
    requested = next(e for e in events if e.event_name == "approval.requested")
    decided = next(e for e in events if e.event_name == "approval.decided")
    assert requested.request_id == id_a and decided.request_id == id_b
    assert requested.approval_id == decided.approval_id == approval.id
    assert requested.tool_call_id == decided.tool_call_id == "private_call"
    for e in events:
        if e.event_name.startswith("tool.execution."):
            assert e.execution_id == execution.id and e.approval_id == approval.id
            assert e.tool_call_id == "private_call" and e.attributes["tool_name"] == "protected"
            assert e.attributes["idempotency_mode"] == "NONE" and e.thread_id == task_id
        if e.event_name.startswith(("workflow.", "llm.")):
            assert e.thread_id == task_id  # Same value today; a separate workflow identity field.
    assert names.index("approval.requested") < names.index("approval.decided")
    assert names.index("tool.execution.claimed") < names.index("tool.execution.succeeded") < names.index("task.completed")
    transitions = [(e.attributes["from_status"], e.attributes["to_status"]) for e in events if e.event_name == "task.state_changed"]
    assert transitions == [("PENDING", "RUNNING"), ("RUNNING", "WAITING_APPROVAL"),
                           ("WAITING_APPROVAL", "RUNNING"), ("RUNNING", "SUCCEEDED")]
    assert_private(events)


@pytest.mark.parametrize("known", [False, True])
def test_failed_and_unknown_execution_events_do_not_leak_exceptions(engine, known):
    error = ToolExecutionFailedWithoutEffect(SECRETS["body"]) if known else RuntimeError(SECRETS["body"])
    sink = InMemoryObservabilitySink()
    with secret_agent(engine, error) as (agent, tool), use_sink(sink):
        task = start(engine, agent)
        approval = pending(engine, task.id)
        with Session(engine) as session:
            with pytest.raises(ToolExecutionFailedWithoutEffect if known else ToolExecutionOutcomeUnknown):
                decide(session, approval.id, runtime=agent)
    expected = TaskStatus.FAILED if known else TaskStatus.RECOVERY_REQUIRED
    assert loaded(engine, task.id).status is expected
    execution_event = next(e for e in sink.events if e.event_name == ("tool.execution.failed" if known else "tool.execution.unknown"))
    assert execution_event.approval_id == approval.id and execution_event.execution_id is not None
    assert execution_event.tool_call_id == "private_call"
    assert execution_event.outcome == ("FAILED" if known else "UNKNOWN")
    assert sink.events[-1].outcome == expected.value
    assert_private(sink.events)


def test_rejected_task_and_approval_are_observable(engine):
    task, approval, agent, _, calls = prepare(engine, approve=False)
    sink = InMemoryObservabilitySink()
    with use_sink(sink), Session(engine) as session:
        decide(session, approval.id, decision="reject")
    assert [e.event_name for e in sink.events] == ["approval.decided", "task.state_changed", "task.completed"]
    assert all(e.task_id == task.id and e.outcome == "REJECTED" for e in sink.events)
    assert sink.events[0].approval_id == approval.id and calls == []


@pytest.mark.parametrize("outcome", ["still_in_progress", "no_action", "orphan_checkpoint", "recovery_required", "recovered"])
def test_recovery_outcomes_and_cache_hit_are_observable(engine, outcome):
    if outcome == "recovery_required":
        task = Task(input=PROMPT)
        task.start()
        with Session(engine) as session:
            TaskRepository(session).save(task)
        agent, _ = runtime(engine, [], [])
        age(engine, task.id)
    else:
        task, approval, agent, _, calls = prepare(engine, approve=outcome not in ("no_action", "orphan_checkpoint"))
        if outcome == "orphan_checkpoint":
            with Session(engine) as session:
                session.delete(session.get(ApprovalRecord, approval.id))
                session.commit()
        if outcome == "recovered":
            agent._approved_execution.execute(task_id=task.id, approval_id=approval.id, tool_call=call(2, True))
            age(engine, task.id)
    sink = InMemoryObservabilitySink()
    with use_sink(sink):
        assert recovery(engine, agent).recover(task.id).outcome.value == outcome
    assert sink.events[0].event_name == "recovery.started"
    assert sink.events[-1].event_name == "recovery.completed" and sink.events[-1].outcome == outcome
    assert all(e.task_id == task.id and e.request_id == sink.events[0].request_id for e in sink.events)
    assert sink.events[0].request_id is not None
    if outcome == "recovered":
        cached = next(e for e in sink.events if e.event_name == "tool.execution.cache_hit")
        assert cached.approval_id == approval.id and cached.execution_id is not None
        assert calls == [2]
    assert_private(sink.events)


def test_broken_sink_does_not_change_recovery(engine):
    task, approval, agent, _, calls = prepare(engine)
    age(engine, task.id)
    sink = BrokenSink()
    with use_sink(sink):
        assert recovery(engine, agent).recover(task.id).outcome.value == "recovered"
    assert loaded(engine, task.id).status is TaskStatus.SUCCEEDED and calls == [2] and sink.calls >= 5


@pytest.mark.parametrize("terminal", ["FAILED", "SUCCEEDED", "WAITING_APPROVAL"])
def test_lost_task_generation_never_emits_false_state_change(engine, terminal):
    task = Task(input=PROMPT)
    task.start()
    with Session(engine) as session:
        TaskRepository(session).save(task)
    newer = Task.restore(**task.model_dump())
    newer.claim_recovery()
    approval = Approval(task_id=task.id, tool_call_id="lost_owner", tool_name="protected", arguments=SECRETS)
    def invoke():
        with Session(engine) as other:
            assert TaskRepository(other).reconcile_if_unchanged(newer, task)
        if terminal == "FAILED":
            raise LLMProviderError(SECRETS["innocent"])
        if terminal == "WAITING_APPROVAL":
            raise ApprovalRequired(approval)
        return AgentResult(content=ANSWER)
    sink = InMemoryObservabilitySink()
    with use_sink(sink), Session(engine) as session:
        with pytest.raises(LLMProviderError if terminal == "FAILED" else TaskOwnershipLost):
            TaskExecutionService(TaskRepository(session), lambda: None, HITLPausePersistence(session)).continue_running(task, invoke)
    assert sink.events == []
    assert loaded(engine, task.id).model_dump() == newer.model_dump()


def test_pause_rollback_emits_no_committed_approval_or_task_event(engine):
    task = Task(input=PROMPT)
    task.start()
    with Session(engine) as session:
        TaskRepository(session).save(task)
        expected = Task.restore(**task.model_dump())
        task.mark_waiting_approval()
        approval = Approval(task_id=task.id, tool_call_id="rollback", tool_name="protected", arguments=SECRETS)
        sink = InMemoryObservabilitySink()
        with use_sink(sink), patch.object(session, "commit", side_effect=SQLAlchemyError(SECRETS["body"])):
            with pytest.raises(SQLAlchemyError):
                HITLPausePersistence(session).save(task, approval, expected=expected)
    assert sink.events == [] and loaded(engine, task.id).status is TaskStatus.RUNNING
    with Session(engine) as session:
        assert ApprovalRepository(session).get_by_id(approval.id) is None


def test_ack_loss_does_not_log_false_success_and_recovery_logs_cache(engine):
    task, approval, agent, _, calls = prepare(engine)
    commits = []
    def sessions():
        session = Session(engine)
        def lose_ack(current):
            commits.append(True)
            if len(commits) == 2:
                raise OperationalError("COMMIT", {}, RuntimeError(SECRETS["token"]))
        event.listen(session, "after_commit", lose_ack)
        return session
    agent._approved_execution._executions = ExecutionRepository(sessions)
    sink = InMemoryObservabilitySink()
    with use_sink(sink), Session(engine) as session:
        with pytest.raises(ExecutionPersistenceUncertain):
            TaskResumeService(session, lambda: agent).resume(task.id, approval.id)
    assert "tool.execution.succeeded" not in [e.event_name for e in sink.events]
    assert "task.completed" not in [e.event_name for e in sink.events]
    assert loaded(engine, task.id).status is TaskStatus.RUNNING and calls == [2]
    age(engine, task.id)
    fresh, _ = runtime(engine, calls, [LLMResponse(content=ANSWER)])
    with use_sink(sink):
        assert recovery(engine, fresh).recover(task.id).outcome.value == "recovered"
    assert calls == [2] and loaded(engine, task.id).status is TaskStatus.SUCCEEDED
    assert "tool.execution.cache_hit" in [e.event_name for e in sink.events]
    assert_private(sink.events)

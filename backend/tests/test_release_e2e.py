"""TASK-032 release qualification through freshly loaded production app wiring."""
from contextlib import contextmanager
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from test_approval_decision import engine
from test_recovery import age, loaded
from test_task_resume import pending
from app.agents.runtime import AgentRuntime
from app.api.dependencies import get_agent_runtime_provider
from app.approvals.repository import ApprovalRepository
from app.core.config import Settings
from app.db.models import ApprovalRecord, ToolExecutionRecord, TaskRecord
from app.executions.models import ToolExecution, ExecutionStatus
from app.executions.repository import ExecutionRepository
from app.llm.client import LLMClient
from app.observability import InMemoryObservabilitySink, use_sink
from app.tasks.models import TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.resume import TaskResumeService
from app.tools.base import Tool
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolResult
from app.workflows.checkpoint import open_checkpointer

PROMPT = "qualification-private-prompt-1237"
ARGUMENT = "qualification-private-argument-2358"
TOOL_RESULT = "qualification-private-tool-result-3469"
FINAL = "qualification-private-answer-4570"


def answer(content=FINAL):
    return {"choices": [{"message": {"content": content}}]}


def tool_request(name="protected", arguments=None, call_id="release_call"):
    return {"choices": [{"message": {"tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments if arguments is not None else {"value": ARGUMENT})}}]}}]}


class PrivateInput(BaseModel):
    value: str


@contextmanager
def application(engine, responses, *, calls=None, sink=None):
    """Only external model/Tool implementations are controlled; services/routes are real."""
    calls = [] if calls is None else calls
    sink = InMemoryObservabilitySink() if sink is None else sink
    requests, savers = [], []
    responses = iter(responses)
    def respond(request):
        requests.append(json.loads(request.content))
        item = next(responses)
        status, body = item if isinstance(item, tuple) else (200, item)
        return httpx.Response(status, json=body)
    class Safe(CalculatorTool):
        def _execute(self, data):
            calls.append("calculator")
            return super()._execute(data)
    class Protected(Tool):
        name, description, input_schema = "protected", "Qualification Tool", PrivateInput
        def _execute(self, data):
            with Session(engine) as observer:
                approval = observer.scalar(select(ApprovalRecord).where(ApprovalRecord.tool_name == self.name))
                assert approval.status == "APPROVED"
                assert observer.get(TaskRecord, approval.task_id).status == "RUNNING"
            assert data.value == ARGUMENT
            calls.append("protected")
            return ToolResult(content=TOOL_RESULT)
    registry = ToolRegistry()
    registry.register(Safe())
    registry.register(Protected())
    @contextmanager
    def saver_factory():
        with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
            savers.append(saver)
            yield saver
    def load(identity):
        with Session(engine) as session:
            return ApprovalRepository(session).get_by_id(identity)
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        settings = Settings(_env_file=None, llm_api_key="qualification-placeholder", llm_base_url="https://controlled.invalid/v1",
                            llm_model="qualification-model", database_url=os.environ["DATABASE_URL"])
        agent = AgentRuntime(LLMClient(settings, transport, sleep_fn=lambda _: None, jitter_fn=lambda _: 0), registry,
            checkpointer_factory=saver_factory, approval_loader=load, execution_repository=ExecutionRepository(lambda: Session(engine)))
        # Execute the real app wiring in a new module namespace, avoiding a duplicate test router.
        spec = spec_from_file_location("qualification_application", Path(__file__).resolve().parents[1] / "app/main.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        fresh_app = module.app
        fresh_app.dependency_overrides[get_agent_runtime_provider] = lambda: lambda: agent
        try:
            with use_sink(sink), TestClient(fresh_app, raise_server_exceptions=False) as client:
                yield SimpleNamespace(client=client, app=fresh_app, agent=agent, calls=calls,
                    requests=requests, savers=savers, sink=sink)
        finally:
            fresh_app.dependency_overrides.clear()
            agent.close()


def run_to_pause(first):
    response = first.client.post("/api/agent/run", json={"message": PROMPT})
    assert response.status_code == 200 and response.json()["status"] == "waiting_approval"
    return UUID(response.json()["task_id"]), UUID(response.headers["X-Request-ID"])


def assert_success(client, task_id, expected=FINAL):
    detail = client.get(f"/api/tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "succeeded" and detail.json()["result"] == expected
    listed = client.get("/api/tasks?status=succeeded")
    assert listed.status_code == 200 and str(task_id) in [item["id"] for item in listed.json()["items"]]


def test_a_plain_assistant_api_task_result_and_correlation(engine):
    with application(engine, [answer()]) as system:
        assert system.client.get("/api/health").status_code == 200
        response = system.client.post("/api/agent/run", json={"message": PROMPT})
        assert response.status_code == 200 and response.json()["answer"] == FINAL
        identity = UUID(response.json()["task_id"])
        assert_success(system.client, identity)
        assert loaded(engine, identity).status is TaskStatus.SUCCEEDED
        assert len(system.requests) == 1 and system.calls == []
        assert all(e.task_id == identity and str(e.request_id) == response.headers["X-Request-ID"] for e in system.sink.events)


def test_b_safe_calculator_needs_no_approval_and_executes_once(engine):
    with application(engine, [tool_request("calculator", {"operation": "add", "a": 2, "b": 3}), answer()]) as system:
        response = system.client.post("/api/agent/run", json={"message": PROMPT})
        assert response.status_code == 200
        identity = UUID(response.json()["task_id"])
        assert_success(system.client, identity)
        assert system.calls == ["calculator"] and len(system.requests) == 2
        assert system.requests[1]["messages"][-1] == {"role": "tool", "content": "5.0", "tool_call_id": "release_call"}
        with Session(engine) as session:
            assert session.scalar(select(ApprovalRecord.id).where(ApprovalRecord.task_id == identity)) is None
            assert session.scalar(select(ToolExecutionRecord.id).where(ToolExecutionRecord.task_id == identity)) is None
        assert "approval.requested" not in [e.event_name for e in system.sink.events]
        assert all(e.task_id == identity for e in system.sink.events)


def test_c_g_fresh_hitl_approve_and_private_cross_request_events(engine):
    calls, sink = [], InMemoryObservabilitySink()
    with application(engine, [tool_request()], calls=calls, sink=sink) as first:
        task_id, request_a = run_to_pause(first)
        approval = pending(engine, task_id)
        evidence = first.agent.workflow_evidence(task_id)
        assert evidence.next_nodes == ("approval_pause",) and calls == []
        assert evidence.values["task_id"] == str(task_id)
    with application(engine, [answer()], calls=calls, sink=sink) as second:
        assert second.app is not first.app and second.agent is not first.agent
        assert second.agent.workflow_evidence(task_id).checkpoint_id == evidence.checkpoint_id
        with patch.object(second.agent, "run", side_effect=AssertionError("initial input must not be resubmitted")):
            response = second.client.post(f"/api/approvals/{approval.id}/approve")
        assert response.status_code == 200 and response.json()["status"] == "approved"
        request_b = UUID(response.headers["X-Request-ID"])
        assert request_a != request_b
        assert_success(second.client, task_id)
        assert calls == ["protected"] and len(second.requests) == 1
        assert second.requests[0]["messages"][-1]["content"] == TOOL_RESULT
        assert not any(a is b for a in first.savers for b in second.savers)
        execution = ExecutionRepository(lambda: Session(engine)).get(task_id, "release_call")
        assert execution.status is ExecutionStatus.SUCCEEDED
    names = [e.event_name for e in sink.events]
    assert {"task.created", "task.completed", "workflow.paused", "workflow.resumed",
            "approval.requested", "approval.decided", "tool.execution.claimed", "tool.execution.succeeded"} <= set(names)
    assert all(e.task_id == task_id and e.request_id in (request_a, request_b) for e in sink.events)
    for e in sink.events:
        if e.event_name.startswith("approval."):
            assert e.approval_id == approval.id
        if e.event_name.startswith("tool.execution."):
            assert e.execution_id == execution.id and e.tool_call_id == "release_call" and e.approval_id == approval.id
        if e.event_name.startswith("workflow."):
            assert e.thread_id == task_id
    serialized = "".join(e.to_json() for e in sink.events)
    assert all(value not in serialized for value in (PROMPT, ARGUMENT, TOOL_RESULT, FINAL))
    assert names.index("approval.requested") < names.index("approval.decided")
    assert names.index("tool.execution.claimed") < names.index("tool.execution.succeeded")


def test_d_rejected_is_not_failed_and_never_executes_tool(engine):
    with application(engine, [tool_request()]) as system:
        task_id, _ = run_to_pause(system)
        approval = pending(engine, task_id)
        response = system.client.post(f"/api/approvals/{approval.id}/reject")
        assert response.status_code == 200 and response.json()["status"] == "rejected"
        assert system.client.get(f"/api/tasks/{task_id}").json()["status"] == "rejected"
        assert loaded(engine, task_id).status is TaskStatus.REJECTED and system.calls == []
        assert len(system.requests) == 1


def test_e_cached_replay_after_result_ack_loss_uses_fresh_api(engine):
    calls, sink = [], InMemoryObservabilitySink()
    with application(engine, [tool_request()], calls=calls, sink=sink) as first:
        task_id, _ = run_to_pause(first)
        approval = pending(engine, task_id)
        commits = []
        def sessions():
            session = Session(engine)
            def lose_ack(current):
                commits.append(True)
                if len(commits) == 2:
                    raise OperationalError("COMMIT", {}, RuntimeError("qualification lost result acknowledgement"))
            event.listen(session, "after_commit", lose_ack)
            return session
        first.agent._approved_execution._executions = ExecutionRepository(sessions)
        assert first.client.post(f"/api/approvals/{approval.id}/approve").status_code == 500
        assert calls == ["protected"]
        assert loaded(engine, task_id).status is TaskStatus.RUNNING
        assert ExecutionRepository(lambda: Session(engine)).get(task_id, "release_call").status is ExecutionStatus.SUCCEEDED
        assert first.agent.workflow_evidence(task_id).next_nodes == ("tool",)
    age(engine, task_id)
    with application(engine, [answer()], calls=calls, sink=sink) as second:
        response = second.client.post(f"/api/tasks/{task_id}/recover")
        assert response.status_code == 200 and response.json()["outcome"] == "recovered"
        assert_success(second.client, task_id)
        assert calls == ["protected"] and len(second.requests) == 1
        assert "tool.execution.cache_hit" in [e.event_name for e in sink.events]


def test_f1_dispatch_loss_recovers_stale_approved_running(engine):
    calls = []
    with application(engine, [tool_request()], calls=calls) as first:
        task_id, _ = run_to_pause(first)
        approval = pending(engine, task_id)
        with patch.object(TaskResumeService, "resume", side_effect=RuntimeError("dispatch lost after claim commit")):
            assert first.client.post(f"/api/approvals/{approval.id}/approve").status_code == 500
        assert loaded(engine, task_id).status is TaskStatus.RUNNING and calls == []
        assert first.agent.workflow_evidence(task_id).next_nodes == ("approval_pause",)
    age(engine, task_id)
    with application(engine, [answer()], calls=calls) as second:
        response = second.client.post(f"/api/tasks/{task_id}/recover")
        assert response.status_code == 200 and response.json()["outcome"] == "recovered"
        assert_success(second.client, task_id)
        assert calls == ["protected"]


def test_f2_unknown_none_is_not_replayed_or_failed(engine):
    with application(engine, [tool_request()]) as system:
        task_id, _ = run_to_pause(system)
        approval = pending(engine, task_id)
        with patch.object(TaskResumeService, "resume", side_effect=RuntimeError("dispatch lost")):
            assert system.client.post(f"/api/approvals/{approval.id}/approve").status_code == 500
        repository = ExecutionRepository(lambda: Session(engine))
        execution, won = repository.claim(ToolExecution(task_id=task_id, approval_id=approval.id,
            tool_call_id=approval.tool_call_id, tool_name=approval.tool_name, arguments=approval.arguments))
        assert won
        repository.finish(execution.finish(ExecutionStatus.UNKNOWN, error_code="outcome_unknown"), expected_updated_at=execution.updated_at)
        age(engine, task_id)
        response = system.client.post(f"/api/tasks/{task_id}/recover")
        assert response.status_code == 200 and response.json()["outcome"] == "recovery_required"
        assert loaded(engine, task_id).status is TaskStatus.RECOVERY_REQUIRED
        assert system.client.get(f"/api/tasks/{task_id}").json()["status"] == "recovery_required"
        assert system.calls == [] and len(system.requests) == 1


def test_f3_completed_checkpoint_reconciles_without_llm_or_tool(engine):
    with application(engine, [answer()]) as first:
        save = TaskRepository.reconcile_if_unchanged
        def lose_task_result(repository, candidate, expected):
            if candidate.status is TaskStatus.SUCCEEDED:
                raise OperationalError("UPDATE", {}, RuntimeError("Task result persistence lost"))
            return save(repository, candidate, expected)
        with patch.object(TaskRepository, "reconcile_if_unchanged", new=lose_task_result):
            assert first.client.post("/api/agent/run", json={"message": PROMPT}).status_code == 500
        with Session(engine) as session:
            task_id = session.scalar(select(TaskRecord.id))
        assert loaded(engine, task_id).status is TaskStatus.RUNNING
        assert first.agent.workflow_evidence(task_id).next_nodes == ()
    age(engine, task_id)
    with application(engine, []) as second:
        response = second.client.post(f"/api/tasks/{task_id}/recover")
        assert response.status_code == 200 and response.json()["outcome"] == "recovered"
        assert_success(second.client, task_id)
        assert second.requests == [] and second.calls == []


@pytest.mark.parametrize("failure", ["provider", "invalid_tool_call", "invalid_tool_name"])
def test_failure_contract_returns_safe_502_and_failed_task(engine, failure):
    responses = ([(503, {"error": ARGUMENT})] * 3 if failure == "provider" else
                 [tool_request(name="" if failure == "invalid_tool_name" else "protected",
                               call_id="" if failure == "invalid_tool_call" else "release_call")])
    with application(engine, responses) as system:
        response = system.client.post("/api/agent/run", json={"message": PROMPT})
        assert response.status_code == 502
        assert ARGUMENT not in response.text
        with Session(engine) as session:
            task_id = session.scalar(select(TaskRecord.id))
        assert loaded(engine, task_id).status is TaskStatus.FAILED
        assert system.client.get(f"/api/tasks/{task_id}").json()["status"] == "failed"
        assert len(system.requests) == (3 if failure == "provider" else 1)
        assert system.calls == []


def test_live_uvicorn_clean_start_with_controlled_http_provider(engine):
    """Real sockets/process, production dependencies; no TestClient overrides."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import socket
    import subprocess
    import sys
    from threading import Thread
    import time

    provider_requests = []
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            provider_requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            data = json.dumps(answer()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = Thread(target=provider.serve_forever, daemon=True)
    worker.start()
    with socket.socket() as reserve:
        reserve.bind(("127.0.0.1", 0))
        port = reserve.getsockname()[1]
    environment = {**os.environ, "LLM_API_KEY": "qualification-placeholder",
        "LLM_BASE_URL": f"http://127.0.0.1:{provider.server_port}/v1", "LLM_MODEL": "qualification-model",
        "LANGSMITH_TRACING": "false"}
    process = None
    try:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
            "--port", str(port), "--log-level", "warning"], cwd=Path(__file__).resolve().parents[1],
            env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            deadline = time.monotonic() + 15
            while True:
                assert process.poll() is None, "Uvicorn exited during clean start"
                try:
                    health = client.get("/api/health")
                    if health.status_code == 200:
                        break
                except httpx.ConnectError:
                    pass
                if time.monotonic() >= deadline:
                    pytest.fail("Uvicorn health deadline exceeded")
                time.sleep(0.05)
            assert UUID(health.headers["X-Request-ID"])
            response = client.post("/api/agent/run", json={"message": PROMPT})
            assert response.status_code == 200 and response.json()["answer"] == FINAL
            task_id = UUID(response.json()["task_id"])
            assert_success(client, task_id)
            assert loaded(engine, task_id).status is TaskStatus.SUCCEEDED
            assert len(provider_requests) == 1
    finally:
        if process is not None:
            process.terminate()
            try:
                _, logs = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                _, logs = process.communicate(timeout=5)
        provider.shutdown()
        provider.server_close()
        worker.join(timeout=5)
    records = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
    assert records and all(record["task_id"] == str(task_id) for record in records)
    assert all(record["request_id"] == response.headers["X-Request-ID"] for record in records)
    assert all(value not in logs for value in (PROMPT, ARGUMENT, TOOL_RESULT, FINAL))

import asyncio
from datetime import datetime, timezone
from io import StringIO
import json
import logging
from threading import Barrier
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.main import ObservedFastAPI
from app.observability import (ObservabilityEvent, ObservabilityContext, current_context,
    observation_context, InMemoryObservabilitySink, StructuredLoggingSink, use_sink, emit)
from app.llm.client import LLMClient, LLMProviderError
from app.llm.schemas import ChatMessage
from test_llm_client import make_settings

SECRET = "private-password-token-email-body-7291"


class BrokenSink:
    def __init__(self):
        self.calls = 0
    def emit(self, event):
        self.calls += 1
        raise RuntimeError(SECRET)


def test_event_serialization_and_allowlist():
    ids = {name: uuid4() for name in ("request_id", "task_id", "thread_id", "approval_id", "execution_id")}
    event = ObservabilityEvent(event_name="tool.execution.claimed", component="execution", **ids,
        tool_call_id="call_123", outcome="EXECUTING", attributes={
            "tool_name": "protected", "argument_count": 5, "idempotency_mode": "NONE",
            "password": SECRET, "innocent_field": SECRET, "arguments": {"x": SECRET},
            "exception": RuntimeError(SECRET), "argument_keys": [SECRET],
            "delay_seconds": float("nan"), "attempt": True})
    data = json.loads(event.to_json())
    assert all(data[key] == str(value) for key, value in ids.items())
    assert data["attributes"] == {"tool_name": "protected", "argument_count": 5, "idempotency_mode": "NONE"}
    assert data["level"] == "INFO" and datetime.fromisoformat(data["timestamp"]).tzinfo is not None
    assert SECRET not in event.to_json()
    assert set(data) == {"event_name", "timestamp", "level", "request_id", "task_id", "thread_id",
                         "approval_id", "execution_id", "tool_call_id", "component", "outcome", "attributes"}
    event.attributes["body"] = SECRET
    assert SECRET not in event.to_json()  # Mutating an attribute cannot bypass output policy.


@pytest.mark.parametrize("changes", [
    {"task_id": object()}, {"tool_call_id": SECRET + "\nbody"},
    {"event_name": SECRET}, {"outcome": SECRET}, {"component": SECRET},
    {"timestamp": datetime(2026, 1, 1)}, {"session": object()},
])
def test_event_rejects_unsafe_envelope(changes):
    with pytest.raises(ValidationError):
        ObservabilityEvent(**{"event_name": "task.created", "component": "task", **changes})


def test_structured_sink_writes_one_parseable_json_record():
    output = StringIO()
    logger = logging.Logger("test-observability", level=logging.INFO)
    logger.addHandler(logging.StreamHandler(output))
    event = ObservabilityEvent(event_name="task.created", component="task", task_id=uuid4())
    StructuredLoggingSink(logger).emit(event)
    assert len(output.getvalue().splitlines()) == 1
    assert json.loads(output.getvalue()) == json.loads(event.to_json())


def test_nested_context_resets_even_on_error_and_does_not_mutate_parent():
    assert current_context() == ObservabilityContext()
    with observation_context(invocation=True, task_id=uuid4()) as parent:
        with pytest.raises(RuntimeError):
            with observation_context(approval_id=uuid4()) as child:
                assert child.request_id == parent.request_id
                assert child.approval_id is not None and parent.approval_id is None
                raise RuntimeError(SECRET)
        assert current_context() == parent
    assert current_context() == ObservabilityContext()


def test_middleware_parallel_requests_and_error_response_are_isolated():
    app = ObservedFastAPI()
    barrier = Barrier(2)
    sink = InMemoryObservabilitySink()
    @app.get("/probe/{task_id}")
    def probe(task_id: UUID):
        with observation_context(task_id=task_id, approval_id=uuid4()):
            barrier.wait(timeout=10)
            emit("task.created", component="task", outcome="PENDING")
            return {"request_id": current_context().request_id, "task_id": current_context().task_id}
    @app.get("/unrelated")
    def unrelated():
        emit("llm.request.started", component="llm", outcome="started")
        return {"task_id": current_context().task_id}
    @app.get("/failure")
    def failure():
        raise RuntimeError(SECRET)
    async def run():
        with use_sink(sink):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                         base_url="http://test") as client:
                tasks = [uuid4(), uuid4()]
                responses = await asyncio.gather(*(client.get(f"/probe/{task}", headers={"X-Request-ID": SECRET}) for task in tasks))
                ids = [UUID(response.headers["X-Request-ID"]) for response in responses]
                assert ids[0] != ids[1]
                for response, task, identity in zip(responses, tasks, ids):
                    assert response.status_code == 200
                    assert response.json() == {"request_id": str(identity), "task_id": str(task)}
                    event = next(e for e in sink.events if e.task_id == task)
                    assert event.request_id == identity and event.approval_id is not None
                other = await client.get("/unrelated")
                assert other.json() == {"task_id": None}
                event = sink.events[-1]
                assert event.request_id == UUID(other.headers["X-Request-ID"])
                assert event.task_id is event.thread_id is event.approval_id is event.execution_id is None
                error = await client.get("/failure")
                assert error.status_code == 500 and UUID(error.headers["X-Request-ID"]) not in ids
            assert current_context() == ObservabilityContext()
    asyncio.run(run())
    assert SECRET not in "".join(event.to_json() for event in sink.events)


@pytest.mark.parametrize("broken", [False, True])
def test_llm_attempt_events_preserve_backoff_and_hide_values(broken):
    sink = BrokenSink() if broken else InMemoryObservabilitySink()
    statuses = iter([503, 429, 200])
    calls, delays = [], []
    def respond(request):
        calls.append(request)
        status = next(statuses)
        return httpx.Response(status, json={"choices": [{"message": {"content": SECRET}}]})
    settings = make_settings()
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        llm = LLMClient(settings, transport, sleep_fn=delays.append, jitter_fn=lambda _: 0)
        with observation_context(invocation=True, task_id=uuid4()) as context, use_sink(sink):
            assert llm.chat([ChatMessage(role="user", content=SECRET)]).content == SECRET
    assert len(calls) == 3 and delays == [1.0, 2.0]
    if broken:
        assert sink.calls == 8
        return
    events = sink.events
    assert [e.event_name for e in events] == [
        "llm.request.started", "llm.request.failed", "llm.retry.scheduled",
        "llm.request.started", "llm.request.failed", "llm.retry.scheduled",
        "llm.request.started", "llm.request.succeeded"]
    assert [e.attributes["attempt"] for e in events] == [1, 1, 1, 2, 2, 2, 3, 3]
    assert [e.attributes["delay_seconds"] for e in events if e.event_name == "llm.retry.scheduled"] == delays
    assert all(e.attributes["max_attempts"] == 3 and e.attributes["model"] == "test-model" for e in events)
    assert all(e.request_id == context.request_id and e.task_id == context.task_id for e in events)
    assert all(e.attributes["retryable"] for e in events if e.event_name == "llm.request.failed")
    serialized = "".join(e.to_json() for e in events)
    assert SECRET not in serialized and settings.llm_api_key not in serialized
    assert settings.llm_base_url not in serialized and "Authorization" not in serialized


def test_nonretryable_llm_failure_records_type_not_exception_text():
    sink = InMemoryObservabilitySink()
    def fail(request):
        raise httpx.RequestError(SECRET, request=request)
    with httpx.Client(transport=httpx.MockTransport(fail)) as transport:
        llm = LLMClient(make_settings(), transport, sleep_fn=lambda _: pytest.fail("must not sleep"))
        with use_sink(sink), pytest.raises(LLMProviderError):
            llm.chat([ChatMessage(role="user", content=SECRET)])
    assert [e.event_name for e in sink.events] == ["llm.request.started", "llm.request.failed"]
    assert sink.events[-1].attributes["retryable"] is False
    assert sink.events[-1].attributes["exception_type"] == "LLMProviderError"
    assert SECRET not in "".join(e.to_json() for e in sink.events)


def test_event_construction_failure_is_best_effort():
    sink = InMemoryObservabilitySink()
    with use_sink(sink):
        emit("task.created", component="task", task_id=object())
        emit("task.created", component="task", task_id=uuid4())
    assert len(sink.events) == 1


@pytest.mark.parametrize("body", ["private invalid JSON", '{"choices": []}'])
def test_invalid_llm_response_is_failed_not_successful_and_never_retried(body):
    from app.llm.client import InvalidLLMResponseError
    sink = InMemoryObservabilitySink()
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=body)
    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        llm = LLMClient(make_settings(), transport, sleep_fn=lambda _: pytest.fail("must not retry"))
        with use_sink(sink), pytest.raises(InvalidLLMResponseError):
            llm.chat([ChatMessage(role="user", content=SECRET)])
    assert len(requests) == 1
    assert [e.event_name for e in sink.events] == ["llm.request.started", "llm.request.failed"]
    assert sink.events[-1].attributes["error_category"] == "invalid_response"
    assert sink.events[-1].attributes["retryable"] is False
    assert all(e.request_id == sink.events[0].request_id for e in sink.events)
    assert sink.events[0].request_id is not None
    assert body not in "".join(e.to_json() for e in sink.events)

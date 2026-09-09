"""Framework-neutral, best-effort lifecycle telemetry; never a durable audit log."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict

from app.observability.context import ObservabilityContext, current_context, observation_context
from app.observability.events import ObservabilityEvent
from app.observability.sinks import ObservabilitySink, StructuredLoggingSink, InMemoryObservabilitySink

_sink: ContextVar[ObservabilitySink] = ContextVar("observability_sink", default=StructuredLoggingSink())


@contextmanager
def use_sink(sink: ObservabilitySink):
    token = _sink.set(sink)
    try:
        yield sink
    finally:
        _sink.reset(token)


def emit(event_name: str, *, component: str, outcome=None, level="INFO", attributes=None, **identities) -> None:
    try:
        context = {**asdict(current_context()), **identities}
        event = ObservabilityEvent(event_name=event_name, component=component, outcome=outcome,
            level=level, attributes=attributes or {}, **context)
        _sink.get().emit(event)
    except Exception:
        # Do not recursively log the failure or include sink exception payloads.
        pass


def task_changed(task, from_status, *, component="task") -> None:
    emit("task.state_changed", component=component, task_id=task.id, outcome=task.status.value,
         attributes={"from_status": from_status.value, "to_status": task.status.value})
    if task.status.value in ("SUCCEEDED", "FAILED", "REJECTED"):
        emit("task.completed", component=component, task_id=task.id, outcome=task.status.value)

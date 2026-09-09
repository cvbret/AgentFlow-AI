from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ObservabilityContext:
    request_id: UUID | None = None
    task_id: UUID | None = None
    thread_id: UUID | None = None
    approval_id: UUID | None = None
    execution_id: UUID | None = None
    tool_call_id: str | None = None


_current = ContextVar("observability_context", default=ObservabilityContext())


def current_context() -> ObservabilityContext:
    return _current.get()


@contextmanager
def observation_context(*, invocation=False, fresh=False, **identities):
    """Nest scoped identities; top-level operator calls get one server UUID."""
    previous = ObservabilityContext() if fresh else current_context()
    if invocation and previous.request_id is None and "request_id" not in identities:
        identities["request_id"] = uuid4()
    token = _current.set(replace(previous, **identities))
    try:
        yield current_context()
    finally:
        _current.reset(token)

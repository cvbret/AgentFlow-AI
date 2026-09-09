import logging
from threading import Lock
from typing import Protocol

from app.observability.events import ObservabilityEvent


class ObservabilitySink(Protocol):
    def emit(self, event: ObservabilityEvent) -> None: ...


class StructuredLoggingSink:
    def __init__(self, logger: logging.Logger | None = None):
        if logger is None:
            logger = logging.getLogger("agentflow.observability")
            if not logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(logging.Formatter("%(message)s"))
                logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.propagate = False
        self._logger = logger

    def emit(self, event: ObservabilityEvent) -> None:
        self._logger.log(getattr(logging, event.level), event.to_json())


class InMemoryObservabilitySink:
    """Test capture only; snapshots prevent cross-thread mutation of stored events."""
    def __init__(self):
        self._records: list[str] = []
        self._lock = Lock()

    def emit(self, event: ObservabilityEvent) -> None:
        record = event.to_json()
        with self._lock:
            self._records.append(record)

    @property
    def events(self) -> list[ObservabilityEvent]:
        with self._lock:
            return [ObservabilityEvent.model_validate_json(record) for record in self._records]

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowEvidence:
    checkpoint_id: str | None
    next_nodes: tuple[str, ...]
    values: dict

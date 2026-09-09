from typing import NotRequired, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt


class AgentGraphState(TypedDict):
    task_id: str  # AgentFlow Task.id; not LangGraph's internal task identifier.
    resume_result: NotRequired[str]
    messages: NotRequired[list[dict]]
    step_count: NotRequired[int]
    max_steps: NotRequired[int]
    final_answer: NotRequired[str]
    tool_calls: NotRequired[list[dict]]
    tool_cursor: NotRequired[int]
    pending_approval: NotRequired[dict | None]
    resume_approval_id: NotRequired[str | None]


def task_id_to_thread_id(task_id: UUID) -> str:
    return str(task_id)


def durable_pause(state: AgentGraphState) -> dict[str, str]:
    # LangGraph replays this node on resume; no side effects precede interrupt.
    result = interrupt({"task_id": state["task_id"], "kind": "durable_pause"})
    if not isinstance(result, str):
        raise ValueError("Foundation resume payload must be a string")
    return {"resume_result": result}


def build_foundation_graph(checkpointer: BaseCheckpointSaver):
    builder = StateGraph(AgentGraphState)
    builder.add_node("durable_pause", durable_pause)
    builder.add_edge(START, "durable_pause")
    builder.add_edge("durable_pause", END)
    return builder.compile(checkpointer=checkpointer)

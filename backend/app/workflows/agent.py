"""Provider-neutral Agent orchestration with a separate replay-safe pause node."""
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.exceptions import AgentMaxStepsExceededError
from app.approved_execution import ApprovedToolExecutionService, ResumeAuthorizationError
from app.llm.client import InvalidLLMResponseError, LLMClient
from app.llm.schemas import ChatMessage, ToolCall
from app.protected_execution import ApprovalRequired, ProtectedToolExecutionService
from app.tools.schemas import ToolMetadata
from app.workflows.graph import AgentGraphState


def route_after_llm(state: AgentGraphState) -> Literal["tool", "__end__"]:
    return END if "final_answer" in state else "tool"


def route_after_tool(state: AgentGraphState) -> Literal["approval_pause", "llm"]:
    return "approval_pause" if state.get("pending_approval") else "llm"


def approval_pause_node(state: AgentGraphState) -> dict:
    # This node may replay. No business writes or Tool calls precede interrupt.
    pending = state["pending_approval"]
    correlation = {"task_id": state["task_id"], "approval_id": pending["id"]}
    resumed = interrupt(correlation)
    if resumed != correlation:
        raise ResumeAuthorizationError("Resume correlation does not match pending Approval")
    return {"resume_approval_id": pending["id"]}


def build_agent_graph(llm_client: LLMClient, tool_definitions: Sequence[ToolMetadata],
                      protected_execution: ProtectedToolExecutionService, *, max_steps: int,
                      checkpointer=None, approved_execution: ApprovedToolExecutionService | None = None):
    def llm_node(state: AgentGraphState) -> dict:
        budget = state.get("max_steps", max_steps)
        if state["step_count"] >= budget:
            raise AgentMaxStepsExceededError(f"Agent exceeded max_steps={budget}")
        response = llm_client.chat(
            messages=[ChatMessage.model_validate(m) for m in state["messages"]], tools=tool_definitions)
        step_count = state["step_count"] + 1
        if not response.tool_calls:
            if response.content is None or not response.content.strip():
                raise InvalidLLMResponseError("LLM response without tool_calls must contain non-empty content")
            return {"step_count": step_count, "final_answer": response.content}
        return {"step_count": step_count,
                "messages": [*state["messages"], ChatMessage(role="assistant", content=response.content,
                             tool_calls=response.tool_calls).model_dump(mode="json")],
                "tool_calls": [call.model_dump(mode="json") for call in response.tool_calls],
                "tool_cursor": 0, "pending_approval": None, "resume_approval_id": None}

    def tool_node(state: AgentGraphState) -> dict:
        messages = list(state["messages"])
        cursor = state["tool_cursor"]
        pending = state.get("pending_approval")
        while cursor < len(state["tool_calls"]):
            call = ToolCall.model_validate(state["tool_calls"][cursor])
            if pending:
                if approved_execution is None or state.get("resume_approval_id") != pending["id"]:
                    raise ResumeAuthorizationError("Missing approved continuation")
                result = approved_execution.execute(approval_id=UUID(pending["id"]),
                    task_id=UUID(state["task_id"]), tool_call=call)
                pending = None
            else:
                try:
                    result = protected_execution.execute(task_id=UUID(state["task_id"]), tool_call=call)
                except ApprovalRequired as signal:
                    if checkpointer is None:
                        raise  # Preserve standalone, non-durable Runtime contract.
                    # Commit completed results and cursor BEFORE entering the interrupt node.
                    return {"messages": messages, "tool_cursor": cursor,
                            "pending_approval": signal.approval.model_dump(mode="json"),
                            "resume_approval_id": None}
            messages.append(ChatMessage(role="tool", tool_call_id=result.tool_call_id,
                                        content=result.content).model_dump(mode="json"))
            cursor += 1
        return {"messages": messages, "tool_cursor": cursor,
                "pending_approval": None, "resume_approval_id": None}

    builder = StateGraph(AgentGraphState)
    builder.add_node("llm", llm_node)
    builder.add_node("tool", tool_node)
    builder.add_node("approval_pause", approval_pause_node)
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", route_after_llm)
    builder.add_conditional_edges("tool", route_after_tool)
    builder.add_edge("approval_pause", "tool")
    return builder.compile(checkpointer=checkpointer)

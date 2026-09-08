"""Provider-neutral, non-checkpointed Agent loop orchestration."""

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.agents.exceptions import AgentMaxStepsExceededError
from app.llm.client import InvalidLLMResponseError, LLMClient
from app.llm.schemas import ChatMessage
from app.protected_execution import ProtectedToolExecutionService
from app.tools.schemas import ToolMetadata
from app.workflows.graph import AgentGraphState


def route_after_llm(state: AgentGraphState) -> Literal["tool", "__end__"]:
    return END if "final_answer" in state else "tool"


def build_agent_graph(
    llm_client: LLMClient,
    tool_definitions: Sequence[ToolMetadata],
    protected_execution: ProtectedToolExecutionService,
    *,
    max_steps: int,
):
    # Dependencies belong to this invocation's closures, never to graph state.
    def llm_node(state: AgentGraphState) -> dict:
        if state["step_count"] >= max_steps:
            raise AgentMaxStepsExceededError(f"Agent exceeded max_steps={max_steps}")
        response = llm_client.chat(
            messages=state["messages"], tools=tool_definitions
        )
        step_count = state["step_count"] + 1
        if not response.tool_calls:
            if response.content is None or not response.content.strip():
                raise InvalidLLMResponseError(
                    "LLM response without tool_calls must contain non-empty content"
                )
            return {"step_count": step_count, "final_answer": response.content}
        return {
            "step_count": step_count,
            "messages": [
                *state["messages"],
                ChatMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                ),
            ],
        }

    def tool_node(state: AgentGraphState) -> dict:
        messages = list(state["messages"])
        # The last assistant message already holds ordered pending ToolCalls.
        for tool_call in state["messages"][-1].tool_calls:
            result = protected_execution.execute(
                task_id=UUID(state["task_id"]), tool_call=tool_call
            )
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=result.tool_call_id,
                    content=result.content,
                )
            )
        return {"messages": messages}

    builder = StateGraph(AgentGraphState)
    builder.add_node("llm", llm_node)
    builder.add_node("tool", tool_node)
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", route_after_llm)
    builder.add_edge("tool", "llm")
    return builder.compile()

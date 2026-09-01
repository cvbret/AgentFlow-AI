# TASK-005 - Minimal Agent Execution Loop

## Status

Not Started

## Objective

Implement the first bounded Agent execution loop using the existing LLMClient,
ToolRegistry, and ToolExecutor.

## Scope

- Add AgentRuntime and AgentResult(content: str).
- Support final answers and sequential tool-call rounds.
- Execute multiple tool calls from one LLM response in order.
- Enforce a required maximum step limit and raise
  AgentMaxStepsExceededError when exceeded.
- Extend chat message models and provider serialization for assistant tool calls
  and tool result messages.
- Add automated runtime and serialization coverage.

## Out of Scope

No FastAPI endpoint, persistence, retries, timeout policy, workflow engine,
LangChain, LangGraph, MCP, multi-agent orchestration, or streaming.

## Verification

Run from backend/:

    .\venv\Scripts\python.exe -m pytest

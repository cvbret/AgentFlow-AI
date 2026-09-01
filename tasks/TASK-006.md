# TASK-006 - Agent API Integration

## Status

Not Started

## Goal

Expose the validated AgentRuntime through one synchronous FastAPI endpoint.

## Scope

- Add POST /api/agent/run.
- Validate a required, non-empty, non-whitespace message.
- Return only the final answer as {answer: string}.
- Wire Settings, LLMClient, ToolRegistry, CalculatorTool, and AgentRuntime.
- Map internal errors to safe HTTP responses.
- Release the process-level LLM HTTP client during application shutdown.
- Add mocked API tests without real provider calls.

## Out of Scope

No persistence, task IDs, async jobs, polling, authentication, streaming,
SSE, WebSocket, LangChain, LangGraph, MCP, or multi-agent orchestration.

## Verification

Run from backend/:

    .\venv\Scripts\python.exe -m pytest

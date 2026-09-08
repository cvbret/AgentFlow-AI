# TASK-027 - AgentRuntime → LangGraph Orchestration Integration

Status: Developer implementation; pending Independent Review.

## Scope

Migrate the existing bounded Agent loop to StateGraph while retaining
AgentRuntime.run(initial_messages, *, task_id) -> AgentResult(content).
Implements ADR-005 incrementally; no additional ADR is needed.

## Implementation

- Per-run compiled graph: START -> llm -> route -> tool / END; tool -> llm.
- AgentGraphState adds optional messages, step_count, final_answer to the
  foundation schema. Last assistant message supplies ordered pending calls.
- LLM and execution dependencies remain outside graph state.
- Agent errors move to agents.exceptions and remain importable from runtime.
- max_steps counts LLM rounds, including the final tool-producing round.
  Its tools execute before exhaustion; final answers on the boundary succeed.
- recursion_limit = 2 * max_steps + 2 is only a framework guard.
- Plain answers preserve original whitespace; empty answers fail as before.
- Multiple calls execute sequentially; errors and ApprovalRequired propagate
  unchanged, stopping later calls and LLM rounds.

## Repository-confirmed clarification

ProtectedToolExecutionService raises ApprovalRequired with an unpersisted Approval.
Existing application code owns atomic pause persistence. No graph interrupt or
approval persistence was added to the runtime.

## Non-goals

No Approval resume, approved Tool execution, real Agent PostgreSQL checkpoint,
dual writes, lifecycle/API changes, ledger, idempotency, reconciliation, queues,
LLMClient rewrite, Tool framework rewrite, AgentExecutor, multi-agent or MCP.
Foundation checkpoint implementation is unchanged. CURRENT_STATE and AI_HANDOFF
remain unchanged pending independent review and project state synchronization.

## Validation

- Focused: `venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_workflow.py tests/test_hitl_pause.py -q`
  — 34 passed, 0 failed, 13 skipped, 0 warnings.
- Full: `venv/Scripts/python.exe -m pytest -q` (also rerun with `-rs` to
  confirm skip reasons) — 223 passed, 0 failed, 70 skipped, 0 warnings.
- All skips require DATABASE_URL, which is absent in this environment.
  No fresh PostgreSQL integration claim is made.
- Existing tests cover plain/single/multiple/multi-round calls, tool result
  history, provider/invalid-response/tool errors and protected pause behavior.
- Added regressions cover final answer at the exact limit, 20-round execution,
  all last-round tools in execution order, error/signal priority, original
  ApprovalRequired identity, input history preservation and repeated-run isolation.
- `git diff --check` passed. No add/commit/push performed.

## Workspace and review handoff

Root and working directory verified as E:\AIProjects\AgentFlow-AI.
Initial branch: main; initial working tree clean.
All edits used repository-relative paths. No repository-external writes detected.
Planned/actual files: agents/runtime.py, agents/exceptions.py,
workflows/graph.py, workflows/agent.py, workflows/__init__.py (under backend/app),
backend/tests/test_agent_runtime.py, backend/tests/test_workflow.py,
docs/ARCHITECTURE.md, and this task file.
No new technical debt recorded. Await Independent Review; this is not a
project-state completion declaration.

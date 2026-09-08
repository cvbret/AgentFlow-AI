# TASK-022 - Protected Tool Execution Request Foundation

## Objective

Create a persistent Approval request for protected ToolCalls without executing side-effectful Tools.

## Scope

- Add a minimal `ProtectedToolExecutionService` orchestration boundary.
- Reuse `ToolExecutionPolicy` for the automatic-execution decision.
- Persist protected requests through `ApprovalRepository.create(...)`.
- Raise an explicit `ApprovalRequired` control signal.

## Requirements

- Safe Tools continue through the existing `ToolExecutor` path.
- Protected Tools create a `PENDING` Approval with the real Task and ToolCall identity.
- Approval persistence failure remains fail closed and never falls back to Tool execution.
- Unknown Tools raise `ToolNotFoundError` and do not create an Approval.
- Existing but unannotated Tools default to `side_effect_free=False` and use the protected Approval path.

## Non-goals

- No TaskStatus changes, Agent pause/resume, Approval API, approved Tool execution, idempotency, retry, or workflow engine.
- `ToolExecutor` must not depend on persistence or Task context.

## Acceptance Criteria

- Safe Tool execution remains unchanged.
- Protected Tool execution never calls `Tool.execute()`.
- The `ApprovalRequired` signal carries the persisted Approval identity.
- Existing Tool, AgentRuntime, and Approval persistence behavior remains compatible.

## Test Plan

- Test safe execution, protected Approval creation, signal identity, zero execution count, and persistence failure fail-closed behavior.
- Test unknown/unannotated Tools and real PostgreSQL Approval round-trip.
- Run existing Tool, Tool Calling, AgentRuntime, Approval, and full regression tests.

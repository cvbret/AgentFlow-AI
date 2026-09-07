# TASK-019 - Side-effect Tool Execution Guard

## Objective

Make Tool execution fail closed for tools that are not declared side-effect-free.

## Scope

- Add a minimal execution policy at the ToolExecutor boundary.
- Allow automatic execution only when `ToolMetadata.side_effect_free` is `True`.
- Reject other tools before `Tool.execute()` using the existing Tool error hierarchy.
- Preserve Registry, provider schema, and AgentRuntime orchestration behavior.

## Requirements

- Calculator remains executable.
- Unknown or unannotated tools default to rejection.
- Side-effectful tools remain registerable and visible to the provider.
- Policy errors must identify protected execution as the missing mechanism.

## Non-goals

- No approval, idempotency, retry, pause/resume, permission system, or new side-effectful tools.
- No changes to Task APIs, persistence, LLM provider schemas, or AgentRuntime policy logic.

## Acceptance Criteria

- `side_effect_free=True` tools execute normally.
- `side_effect_free=False` tools fail before their implementation runs.
- Existing Calculator tool-calling and provider schema tests remain green.

## Test Plan

- Test Calculator allowance and existing AgentRuntime tool calling.
- Test policy rejection and zero execution count for an unannotated tool.
- Test Registry registration/listing and provider schema compatibility.


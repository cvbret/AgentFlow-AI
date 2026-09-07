# TASK-018 - Tool Execution Safety Metadata Foundation

## Objective

Add minimal explicit side-effect safety metadata to the existing Tool metadata
without changing tool execution behavior.

## Scope

- Add `side_effect_free` to `ToolMetadata` with a safe default of `False`.
- Preserve the default for existing and future unannotated tools.
- Mark the Calculator tool as explicitly side-effect free.
- Preserve Registry, Executor, and provider schema behavior.

## Requirements

- `True` means the tool does not change external persistent state.
- Safety metadata is internal and must not be included in provider tool JSON.
- Existing tool construction and execution contracts remain compatible.

## Non-goals

- No approval, blocking, retry, idempotency, persistence, or new tool framework.
- No new tools or changes to tool execution semantics.

## Acceptance Criteria

- Unknown or unannotated tools expose `side_effect_free=False`.
- Calculator metadata exposes `side_effect_free=True`.
- Registry and Executor behavior remains unchanged.
- Provider schemas contain only the existing provider-facing fields.

## Test Plan

- Test metadata defaults and Calculator metadata.
- Test Registry metadata preservation and unchanged execution.
- Test provider schema isolation and existing tool/runtime regressions.

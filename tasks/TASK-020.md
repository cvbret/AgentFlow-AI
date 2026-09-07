# TASK-020 - Approval Domain Model Foundation

## Objective

Establish an independent Approval domain entity for protected ToolCall decisions.

## Scope

- Add `ApprovalStatus` with `PENDING`, `APPROVED`, and `REJECTED`.
- Add an Approval entity with its own identity, Task/ToolCall association, arguments snapshot, and decision timestamps.
- Enforce pending and terminal state invariants and legal decision transitions.

## Requirements

- New approvals start as `PENDING` with no `decided_at`.
- Only `PENDING → APPROVED` and `PENDING → REJECTED` are valid transitions.
- Timestamps are UTC-aware and arguments are copied at construction.
- Use the existing domain-model style without adding a generic state-machine framework.

## Non-goals

- No Approval persistence, API, TaskStatus changes, Tool execution integration, pause/resume, approval workflow, or idempotency.

## Acceptance Criteria

- Approval identity and Task/ToolCall fields are represented in the domain model.
- Approval decisions set `decided_at` and terminal decisions cannot be overwritten.
- Invalid state and timestamp combinations are rejected.

## Test Plan

- Test creation, approval, rejection, invalid transitions, UTC timestamps, invariants, associations, and arguments snapshot behavior.
- Run existing Task, Tool, Tool Calling, and full regression tests.

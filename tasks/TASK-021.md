# TASK-021 - Approval Persistence Foundation

## Objective

Persist the Approval domain entity in PostgreSQL while preserving domain and ORM separation.

## Scope

- Add an Approval ORM model and PostgreSQL `approvals` table.
- Add `ApprovalRepository.create`, `get_by_id`, and `save`.
- Map persisted rows through `Approval.restore(...)`.
- Add the Task foreign key, JSON arguments storage, and migration tests.

## Requirements

- Persist Approval identity, Task/ToolCall association, arguments, status, and timestamps.
- Follow the existing Session, commit, rollback, and Alembic conventions.
- Reject invalid persisted Approval state through the domain contract.

## Non-goals

- No Approval API, Agent integration, Tool policy integration, pause/resume, listing, pagination, bulk operations, or idempotency.
- No generic repository or mapper framework.

## Acceptance Criteria

- Pending, approved, and rejected Approvals round-trip through PostgreSQL.
- Nested arguments and identity fields are preserved.
- Task foreign-key integrity is enforced.
- Create/save database failures rollback without closing the injected Session.

## Test Plan

- Run Approval PostgreSQL integration tests for create, restore, update, FK, invalid state, and rollback behavior.
- Run Task persistence, domain, Tool, Tool Calling, and full regression tests.

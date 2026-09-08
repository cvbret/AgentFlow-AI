# TASK-024 - Approval Decision Integration Foundation

## Objective

Expose reliable Approval decisions through an application Service and HTTP API without executing or resuming a Task.

## Scope

ApprovalDecisionService, request-scoped dependency wiring, approve/reject endpoints, conditional decision persistence, and PostgreSQL concurrency regressions.

## Requirements

- Reuse Approval.approve()/reject() to create legal terminal candidates.
- Load the associated Task and require WAITING_APPROVAL; missing/nonwaiting context is rejected with 409.
- Persist only status and decided_at using one conditional UPDATE WHERE id matches AND status=PENDING; also guard task identity and current WAITING_APPROVAL context in SQL.
- Return True for one updated row and False for zero. Zero means conflict, not inferred terminal state.
- Unknown Approval is 404; terminal/duplicate/concurrent decisions are 409. Persistence errors rollback and propagate rather than becoming conflicts.
- POST /api/approvals/{approval_id}/approve and /reject return 200 with approval_id, task_id, lowercase status and decided_at after commit.
- Preserve Approval identity, arguments and creation timestamp, and leave Task unchanged.

## Non-goals

No resume, checkpoint, Tool execution, Task lifecycle transition, idempotency, reconciliation, queue, worker, or new framework. Existing standalone Repository methods remain compatible; no schema migration.

## Acceptance Criteria

Approve and reject persist. Concurrent approve/reject and same-decision attempts have exactly one winner and one conflict. The winning timestamp is not overwritten. Task remains WAITING_APPROVAL and no Tool or Runtime executes. Database failure is not misclassified as conflict.

## Test Plan

Run real PostgreSQL API, context, identity, terminal, synchronized two-Session concurrency and trigger failure tests, then existing Approval/Task/HITL/Agent/API regressions and full suite. Await Independent Review before project completion synchronization.

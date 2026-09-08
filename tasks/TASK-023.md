# TASK-023 - HITL Pause Integration Foundation

## Objective

Persist a pending Approval for a protected ToolCall and pause its Task in WAITING_APPROVAL without executing the Tool.

## Contract

- Task lifecycle: PENDING → RUNNING → SUCCEEDED / FAILED / WAITING_APPROVAL.
- Only RUNNING may enter WAITING_APPROVAL through `mark_waiting_approval()`; no outgoing transition is implemented. Waiting Tasks have no result or error.
- `AgentRuntime.run` requires the real `task_id`. Each run creates a local `ProtectedToolExecutionService`; the shared Runtime retains no Session or Task context.
- Safe Tools execute through ToolExecutor and the Agent loop continues. Protected requests construct an unpersisted Approval carried by ApprovalRequired, which immediately stops the loop. The identity fields remain available; the signal no longer proves persistence.
- TaskExecutionService catches ApprovalRequired separately, creates a waiting candidate using Task.restore and the domain transition, and calls HITLPausePersistence to stage Approval + Task WAITING on one Session with one commit before returning the candidate Task. Other execution exceptions persist FAILED and are re-raised with safe stored error text.
- Pause persistence failure rolls back both writes; the original RUNNING Task is unchanged, then transitions legally to FAILED and is saved best-effort in a separate transaction. The original exception propagates and no waiting success is returned. FAILED persistence may itself fail. The short pause transaction starts only after the protected request is identified; no transaction spans LLM execution.
- POST /api/agent/run returns HTTP 200 with task_id, status (succeeded or waiting_approval), and nullable answer. Paused answer is null. Task query/list uses lowercase waiting_approval.
- Task status uses VARCHAR(32); no migration or Task approval_id field is required.

## Non-goals

No approval decision API, resume, checkpoint, approved Tool execution, idempotency, retry, new framework, or workflow engine. Earlier safe Tool results and remaining ToolCalls are not checkpointed for replay.

## Acceptance / Verification

Test legal/illegal transitions and restore invariants; unchanged signal propagation and immediate stop; safe exactly-once execution; pending Approval persistence and Task waiting round-trip; SQL status filtering; Approval commit failure and ordinary execution failures; waiting-state save failure. Run focused and full suites against an isolated PostgreSQL database. Implementation awaits Independent Review before project completion state synchronization.

Atomic verification includes real PostgreSQL INSERT/WAITING UPDATE failure triggers and a deferred COMMIT failure trigger, independent Session visibility, one pause commit, staging rollback, and API failure responses. See revised ADR-003 and closed TD-006.

Commit-uncertainty protection: failure candidates still use Task.fail(), but save_failed_if_running performs one SQL UPDATE conditioned on durable RUNNING and returns whether one row changed. Zero rows never confirms pause success. A real PostgreSQL commit followed by simulated acknowledgement loss must preserve WAITING_APPROVAL + PENDING Approval while the original error propagates (HTTP 500 permitted). Standalone save and atomic pause are unchanged.

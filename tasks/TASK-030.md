# TASK-030 - Resume Reliability / Recovery

Status: Developer focused fixes; pending Focused Re-Review. ADR-008 remains pending Independent Review.

## Initial Implementation Workspace / Planned Write Set

Root and verified working directory: E:\AIProjects\AgentFlow-AI.
Branch main, initially clean and up to date with origin/main.
All writes use contained repository-relative paths.

Planned/actual files:

- .env.example
- backend/app/core/config.py
- backend/app/tasks/models.py
- backend/app/tasks/repository.py
- backend/app/tasks/service.py
- backend/app/tasks/recovery.py (new)
- backend/app/executions/repository.py
- backend/app/executions/recovery.py (new)
- backend/app/approved_execution.py
- backend/app/agents/runtime.py
- backend/app/workflows/recovery.py (new evidence DTO; Graph state unchanged)
- backend/app/api/dependencies.py
- backend/app/api/tasks.py
- backend/tests/test_recovery.py (new)
- backend/tests/test_task_repository.py
- backend/tests/test_task_resume.py
- docs/ARCHITECTURE.md
- docs/DECISIONS.md (append ADR-008; history unchanged)
- tasks/TASK-030.md (new)

## State / Classification

RECOVERY_REQUIRED means durable facts cannot safely establish continuation, not
known failure or human rejection. Active RUNNING/WAITING_APPROVAL may enter it;
only an evidence-backed optimistic claim permits RECOVERY_REQUIRED -> RUNNING.
Task result/error remain empty; Task Query/filter supports the new state.

Outcomes: RECOVERED, NO_ACTION, STILL_IN_PROGRESS, RECOVERY_REQUIRED,
ORPHAN_CHECKPOINT (serialized lowercase). Recovery API exposes only task_id/outcome.
Healthy waiting is read-only. Recent Task or ledger activity does not dispatch.
Missing/incompatible waiting/stale active checkpoint requires review. Orphans and
incompatible terminal state are reported without deleting or changing checkpoints.

RECOVERY_STALE_AFTER_SECONDS defaults to 300, configurable, positive and finite.
Both Task.updated_at and ToolExecution.updated_at are used; a timestamp does not
prove an old actor died. No production threshold is embedded in policy code.

## Concurrency / Execution Policy

Task status/updated_at conditional persistence claims dispatch, strictly advances
timestamp and commits first. A losing request cannot dispatch. Completed Graph
reconciliation uses the same conditional update and cannot overwrite newer state.

Ordinary ApprovedToolExecutionService still denies EXECUTING/UNKNOWN/FAILED and
reuses SUCCEEDED. ExecutionRecoveryService validates persisted APPROVED Approval
and complete context, then permits a single stale EXECUTING/UNKNOWN attempt only
for EXTERNAL_KEY or INHERENT. It conditionally claims the same execution UUID/key.
Claim/result transactions never span external execution. Normal/recovery result
writes include expected claim timestamp; stale owners cannot overwrite a new claim.
NONE never executes. Repeated ambiguity records UNKNOWN and requires Task review.

After a successful execution recovery, the graph consumes its stored result through
ordinary approved execution. Runtime provides checkpoint evidence and a restricted
pending-tool continuation entry point; API never accesses graph internals.
Existing TaskResumeService/TaskExecutionService handles success, known failures and
another protected pause. Normal uncertain/blocked execution now enters
RECOVERY_REQUIRED instead of generic FAILED; known failures remain FAILED.

## PostgreSQL Acceptance Evidence

New test_recovery.py: 33 cases (29 real PostgreSQL, 4 configuration/unit cases).

- Stale APPROVED/RUNNING at approval_pause: recover invokes existing Runtime.resume,
  executes once and persists SUCCEEDED.
- SUCCEEDED ledger with graph at approval_pause OR failed tool node: fresh runtime
  recovery uses cached result. Tool side-effect count before = 1; after = 1.
- Stale EXECUTING and UNKNOWN with NONE: no Tool call, Task RECOVERY_REQUIRED.
- Both statuses with EXTERNAL_KEY/INHERENT: same execution ID/key; external fake
  endpoint sees the same key twice but one operation, inherently idempotent setter
  retains one final value. Recovery completes SUCCEEDED.
- Recovery again ambiguous: ledger UNKNOWN, Task RECOVERY_REQUIRED, one attempt;
  immediate further operator request does not execute again.
- Normal ambiguous execution enters RECOVERY_REQUIRED and subsequently recovers
  via external-key contract; this is not a terminal FAILED reopening.
- Completed Graph/RUNNING Task: persist durable final answer without LLM/Tool.
  A competing Task state change defeats reconciliation instead of being overwritten.
- Matching PENDING/waiting pause: no state/checkpoint changes.
- Missing checkpoint: persist RECOVERY_REQUIRED. Orphan Task/Approval and rejected
  terminal checkpoint: ORPHAN_CHECKPOINT; checkpoint identity remains unchanged.
- Concurrent recovery requests: exactly one resume dispatch; the other returns
  STILL_IN_PROGRESS. Recent Task/EXECUTING activity does not dispatch.
- Commit APPROVED/RUNNING then lose acknowledgement: fresh runtime/recovery reads
  committed truth and safely completes.
- Old execution writer is rejected after a newer execution recovery claim.
- Recovery API response/filter verified; RECOVERY_REQUIRED can return to RUNNING
  only through successful safe claim. Approval/context mismatch and missing Tool
  capability fail closed. Recovery can pause again for a second Approval.

## Migration / Validation

Task status is already VARCHAR(32), with no database enum/check requiring a schema
change. RECOVERY_REQUIRED fits the existing schema; no empty migration is added.
A fresh temporary PostgreSQL 17 database was upgraded through Alembic 0001, 0002,
0003; explicit workflow setup initialized checkpoint tables. No real external
provider calls or skipped PostgreSQL acceptance tests.

Initial implementation runs (before focused review):

- Focused: `venv/Scripts/python.exe -m pytest tests/test_recovery.py tests/test_execution_ledger.py tests/test_task_resume.py -q`
  — 84 passed, 0 failed, 0 skipped, 0 warnings (18.71 seconds).
- Full PostgreSQL regression: `venv/Scripts/python.exe -m pytest -q`
  — 378 passed, 0 failed, 0 skipped, 0 warnings (30.83 seconds).
- Initial full run found the existing all-status fixture missing the new enum
  member. Added RECOVERY_REQUIRED fixture data, preserving the all-status assertion.
- Direct resume failure test now expects RECOVERY_REQUIRED for an uncertain Tool
  outcome, while input/provider/budget failures retain their known-failure contract.

## Remaining Limits / Non-goals

No universal exactly-once. No background automatic recovery.

Staleness is not proof of actor termination; this is an optimistic timestamp claim,
not a long-lived lease. Idempotent recovery relies on declared Tool/provider
semantics. Unsupported intermediate graph shapes and incompatible existing terminal
FAILED/REJECTED records remain operator concerns and are not silently reopened.
Cross-store facts can change; changed checkpoint identity suppresses dispatch.
No background scanner, polling, scheduler, queue, worker, heartbeat framework,
force replay, orphan deletion, compensation, 2PC, MCP or multi-agent is implemented.

## Initial Implementation Review Handoff (before focused fixes)

CURRENT_STATE and AI_HANDOFF unchanged. ADR-008 proposed pending Independent Review.
Final git diff --check passed. All 19 files (14 modified, 5 new) are in the
planned scope; no staged changes. Repository-relative writes used; no external
source/document writes detected. Temporary PostgreSQL container and volumes
removed. No add/commit/push. Stop for Independent Review.


## Focused Fix / Planned Write Set

Scope: only the two Independent Review IMPORTANT findings. No TASK-030 rewrite.
Focused-fix entry state was main with 14 modified tracked files and 5 untracked
TASK-030 files; the earlier clean-entry statement refers to initial implementation.
Verified working directory and Git root: E:\AIProjects\AgentFlow-AI.
All writes use repository-relative paths with resolved containment checks.

Actual focused changes (16 files):

- backend/app/tasks/service.py
- backend/app/tasks/repository.py
- backend/app/tasks/pause_persistence.py
- backend/app/executions/exceptions.py
- backend/app/executions/repository.py
- backend/tests/test_recovery.py
- backend/tests/test_execution_ledger.py
- backend/tests/test_task_service.py
- backend/tests/test_task_repository.py
- backend/tests/test_hitl_pause.py
- backend/tests/test_approval_decision.py
- backend/tests/test_task_resume.py
- backend/tests/test_protected_execution.py
- docs/ARCHITECTURE.md
- docs/DECISIONS.md (update ADR-008 itself; status still pending Independent Review)
- tasks/TASK-030.md

The initially announced conditional approved_execution.py adjustment proved
unnecessary; its earlier TASK-030 changes are preserved. test_agent_api.py was
included in planned validation/adaptation but needed no edit. The three additional
pause-interface test files were announced before editing and stay in this scope.

## IMPORTANT 1 / Task Lifecycle Ownership Evidence

TaskExecutionService captures an independent RUNNING snapshot before invoking
Runtime. Every lifecycle write compares the Task ID, RUNNING status and exact
captured updated_at generation; it never reloads a newer owner to justify an old
actor's write. A recovery claim strictly advances this generation.

- FAILED: save_failed_if_running requires the original snapshot. A lost CAS
  preserves the original exception and performs no fallback write.
- SUCCEEDED: conditional reconciliation replaces unconditional save. Losing
  ownership raises TaskOwnershipLost without a FAILED fallback.
- WAITING_APPROVAL: the conditional update and Approval INSERT share one short
  transaction. A lost generation raises TaskOwnershipLost, rolls back the new
  Approval and cannot return a successful pause or trigger generic FAILED.
- RECOVERY_REQUIRED reconciliation also uses the captured snapshot.

Real PostgreSQL regression uses two Runtime/TaskResumeService actors with explicit
TaskRecoveryService takeover. A is blocked inside its external-key Tool while B
commits newer Task and Execution claims. A then returns late; its Execution finish
raises ExecutionPersistenceConflict and its Task FAILED conditional update returns
False while B remains RUNNING. B completes and its graph consumes the ledger cache.
The logical clock is advanced for inactivity classification; neither actor's
captured database generation is rewritten to manufacture a conflict.

Observed final evidence:

- Task = SUCCEEDED, result = B completed.
- Ledger = SUCCEEDED; the same execution UUID and idempotency key are retained.
- Tool calls = 2 (A and the explicitly authorized B recovery attempt).
- External effects = 1; the fake provider honors their shared idempotency key.
- B LLM calls = 1; A's failed Task write outcomes = [False].

A separate three-case PostgreSQL regression proves old FAILED/SUCCEEDED/
WAITING_APPROVAL candidates cannot alter a new RUNNING generation; no orphan
Approval remains after the rejected waiting write.

## IMPORTANT 2 / Persistence Acknowledgement Uncertainty

ExecutionPersistenceUncertain represents unconfirmed local ledger durability,
not an external UNKNOWN outcome and not a known execution failure. The repository
wraps SQLAlchemy errors after transaction-body completion (claim/recovery/result
commit acknowledgement) and errors persisting a Tool result, retaining the cause.
A failed result write cannot justify calling the Tool again or declaring its Task
FAILED. Ownership conflicts retain their separate exception.

TaskExecutionService propagates this signal without changing RUNNING. Subsequent
operator recovery re-reads persisted Task, Approval, ledger and checkpoint facts;
it does not guess whether the prior commit happened. Explicit known no-effect Tool
failures still persist FAILED, while external ambiguity retains RECOVERY_REQUIRED.

The full application-path test invokes TaskResumeService -> AgentRuntime ->
approved Tool -> real PostgreSQL SUCCEEDED commit. An after_commit injection then
raises OperationalError. Fresh reads prove the committed result, and a fresh
Runtime/TaskRecoveryService completes the pending tool checkpoint from cache.

Observed evidence:

- Tool calls before recovery = 1; after recovery = 1.
- Task before recovery = RUNNING, identical durable snapshot to before resume.
- Task after recovery = SUCCEEDED, result = cached recovery completed.
- Ledger before/after = SUCCEEDED; Approval remains APPROVED.
- Checkpoint before = tool; after = END; fresh LLM calls = 1 and consumes cached content.

## Focused Regression / Validation

Six new PostgreSQL cases cover three lifecycle exits, the late executor race,
the full application result-commit acknowledgement fault, and known no-effect
Tool failure (Task FAILED, Ledger FAILED, effect count 0).
Existing normal success, subsequent pause, input/provider/budget failures,
external UNKNOWN, concurrent recovery, stale capability checks and cached replay
remain covered. No test was deleted or assertions weakened.

Validation uses a fresh temporary PostgreSQL 17 database migrated to Alembic 0003
plus explicit LangGraph checkpoint setup. No real external provider calls.

- First focused run: 173 passed, 2 failed. The existing concurrency barrier also
  caught the newly conditional success write, and one pause mock lacked expected.
  Restricted the barrier to claims and supplied/asserted the original snapshot.
- Intermediate focused run: 175 passed, 0 failed, 0 skipped, 0 warnings.
- First full run: 382 passed, 1 failed. A direct protected pause test lacked expected;
  updated that caller without changing its durable-approval assertions.
- Final focused command: `venv/Scripts/python.exe -m pytest tests/test_recovery.py tests/test_execution_ledger.py tests/test_task_resume.py tests/test_task_service.py tests/test_task_repository.py tests/test_hitl_pause.py tests/test_approval_decision.py tests/test_agent_api.py tests/test_protected_execution.py -q`
  Result: 181 passed, 0 failed, 0 skipped, 0 warnings (19.56 seconds).
- Final full PostgreSQL command: `venv/Scripts/python.exe -m pytest -q`
  Result: 384 passed, 0 failed, 0 skipped, 0 warnings (25.47 seconds).

## Focused Scope / Git / Workspace Audit

No new Task, worker, queue, heartbeat, lease framework, automatic UNKNOWN
reconciliation, distributed scheduler, orphan deletion or universal exactly-once
claim. No dependencies or schema migrations added. Timestamp ownership remains
optimistic; explicit external idempotency still depends on the Tool/provider
contract. Unconfirmed non-SUCCEEDED facts retain existing operator recovery rules.

Git actual combined working tree: 21 modified tracked files, 5 untracked files,
0 staged files. This includes the earlier TASK-030 implementation, not 26 new
focused-fix changes. The 16 files listed above are the actual focused write set.
The other 10 preserved TASK-030 files are .env.example, agents/runtime.py,
api/dependencies.py, api/tasks.py, approved_execution.py, core/config.py,
tasks/models.py, executions/recovery.py, tasks/recovery.py and workflows/recovery.py
(all Python paths under backend/app/).

Root and working directory verified; all source/document writes used contained
repository-relative paths. No repository-external file creation, modification,
moving or deletion detected. The dedicated agentflow-task030-fix-test PostgreSQL
container and its volumes were removed after testing. No git add, commit or push.
Git diff --check passed; CURRENT_STATE and AI_HANDOFF have no changes. ADR-008
remains pending Independent Review. Stop here for Focused Re-Review.

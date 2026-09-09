# TASK-029 - Protected Tool Idempotency / Execution Ledger

Status: Developer implementation; pending Independent Review.

## Workspace / Planned Write Set

Repository and working directory: E:\AIProjects\AgentFlow-AI.
Branch main; initial status clean and up to date with origin/main.
Source/document writes use repository-relative paths with containment verification.

Planned/actual files:

- backend/app/executions/__init__.py (new)
- backend/app/executions/models.py (new)
- backend/app/executions/exceptions.py (new)
- backend/app/executions/repository.py (new)
- backend/app/db/models/tool_execution.py (new)
- backend/app/db/models/__init__.py
- backend/alembic/versions/0003_create_tool_executions.py (new)
- backend/app/approved_execution.py
- backend/app/tools/base.py
- backend/app/tools/schemas.py
- backend/app/tools/exceptions.py
- backend/app/agents/runtime.py
- backend/app/api/dependencies.py
- backend/tests/test_execution_ledger.py (new)
- backend/tests/test_task_resume.py (ledger dependency wiring only)
- backend/tests/test_approval_decision.py (shared fixture clears ledger before FK parents)
- docs/ARCHITECTURE.md
- docs/DECISIONS.md (append ADR-007, historical ADRs unchanged)
- tasks/TASK-029.md (new)

## Execution Identity / State Machine

ToolExecution has an independent UUID, Task/Approval correlation, ToolCall identity,
name, arguments, status, UUID-derived stable idempotency_key, result_content,
error_code and UTC timestamps. Database UNIQUE(task_id, tool_call_id) selects one
business execution; the idempotency key is also unique. Domain and ORM are separate.

EXECUTING is a durable claim, not evidence that an effect is absent. SUCCEEDED
requires durable result and permits cache reuse only. FAILED records an explicit
ToolExecutionFailedWithoutEffect signal. UNKNOWN records explicit uncertain or
generic execution errors; automatic replay is blocked. Existing EXECUTING and
FAILED also block replay. Terminal records cannot be transitioned again.

Canonical JSON comparison sorts keys, preserves JSON type differences and rejects
non-finite values. Approval ID/name/arguments mismatch under an existing business
key fails closed. Persisted APPROVED Approval and full context remain mandatory
before a successful cached result can be returned.

## Transaction / Tool Boundaries

ExecutionRepository owns short-lived Sessions. INSERT ON CONFLICT and its commit
precede Tool execution; result/failure persistence uses a separate conditional
EXECUTING-to-terminal transaction. No DB transaction spans external effects.
Read-before-claim is only an optimization; uniqueness decides concurrent winners.

Reuse Registry resolution and Tool input validation before claim. Invalid input
creates no claim and no effect. Existing Tool.execute/data and Calculator remain
compatible. Generic errors cannot establish a definitive failed external outcome;
only explicit known-no-effect signals become FAILED. Error storage contains safe
classification codes. Result-write errors never trigger a second Tool call.

Tool capability NONE is the default. EXTERNAL_KEY invokes an explicit context hook
with the stored stable key; INHERENT is descriptive. Neither grants retry rights.
Tools receive no repository. ApprovalDecision/Graph state/API lifecycle are not
redesigned; Runtime and dependency assembly only inject the ledger repository.

## Acceptance Evidence

New test_execution_ledger.py contains 26 cases (19 PostgreSQL, 7 unit/domain):

- First execution observes committed EXECUTING from another Session before its
  effect, stores SUCCEEDED and content; fresh service reuses result with count 1.
- Graph progress-loss proof: durable approved pause, commit authorization, execute
  Tool and persist SUCCEEDED, inject node failure before graph progress advances,
  close graph/saver, then create fresh graph/saver and perform controlled replay.
  Tool effect count before replay = 1; after replay = 1. Cached Tool result reaches
  the LLM and the graph produces its final answer. No recovery API/scanner is added.
- Real PostgreSQL concurrent executors both inspect absent identity; one INSERT
  claim wins, the other observes EXECUTING and blocks. At most one Tool execution;
  database has exactly one execution row.
- Existing business-key mismatch in approval ID, name or arguments fails closed.
  Reordering arguments is accepted; changing JSON types is not identical.
- Explicit UNKNOWN and generic ambiguous errors persist UNKNOWN, and replay never
  calls the Tool. Explicit known-no-effect failure persists FAILED and blocks retry.
- External fake endpoint receives the durable key. Service replay uses cache;
  an explicit repeated operation-contract call with the same key deduplicates at
  the fake endpoint; a different execution gets a different key. No network use.
- Existing EXECUTING blocks even EXTERNAL_KEY Tools. Validation failure creates no
  claim. Missing external-key context fails before the effect.
- PostgreSQL INSERT/result UPDATE trigger failures and actual commit-then-lost-ack
  simulations verify no blind reexecution. A lost claim ack leaves EXECUTING and
  no effect; lost success ack leaves SUCCEEDED and replay returns stored result.
- Claim losers load the original UUID/key; authorization remains required even
  when a successful ledger result exists. Domain invariants/terminal writes tested.

All TASK-028 resume tests pass with the ledger dependency. Historical durable
foundation proof is not independently repeated beyond normal full regression.

## PostgreSQL Migration / Validation

Temporary PostgreSQL 17, isolated test databases; no real external provider calls.

- Alembic upgrade from empty -> 0001 -> 0002 -> 0003 passed.
- Downgrade 0003 -> 0002 and upgrade -> 0003 passed on the temporary database.
- Explicit checkpoint setup prepares the combined integration database.
- Focused: `venv/Scripts/python.exe -m pytest tests/test_execution_ledger.py tests/test_task_resume.py tests/test_tools.py tests/test_tool_calling.py -q`
  — 75 passed, 0 failed, 0 skipped, 0 warnings (6.95 seconds).
- Full PostgreSQL regression: `venv/Scripts/python.exe -m pytest -q`
  — 344 passed, 0 failed, 0 skipped, 0 warnings (14.62 seconds).
- Additional raw `alembic check` against the combined database reported LangGraph
  checkpoint tables as unowned removal differences. No generated removal or DDL
  was applied. A fresh business-only database was migrated and `alembic check`
  passed: No new upgrade operations detected. Alembic/checkpointer ownership was
  preserved without expanding this task into foundation/schema-management changes.

## Remaining Ambiguous Window / Non-goals

No universal crash-safe exactly-once guarantee.

Tool success + ledger SUCCEEDED + lost graph progress is covered by cached replay.
Tool external effect + crash before ledger success remains ambiguous EXECUTING;
recorded UNKNOWN also fails closed. No automatic stale recovery, UNKNOWN
reconciliation, background retry, Task scanning, queue, worker, scheduler,
lease/heartbeat, outbox, saga, two-phase commit, orphan checkpoint cleanup,
MCP or multi-agent is implemented. These remain TASK-030/recovery operations scope.

## Git / Review Handoff

All 19 changed/new files are in the planned repository scope. CURRENT_STATE and
AI_HANDOFF remain unchanged. ADR-007 is proposed pending Independent Review.
Final git diff --check passed; 11 modified and 8 untracked files, no staged changes.
No repository-external source/document writes detected. Temporary PostgreSQL
container and volumes removed. No git add/commit/push. Stop for Independent Review.

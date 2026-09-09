# TASK-031 - Observability Foundation

Status: Developer implementation; pending Independent Review.

## Workspace / Planned Write Set

Repository and working directory verified: E:\AIProjects\AgentFlow-AI.
Initial Git state: main, clean, up to date with origin/main; no staged changes.
The pre-existing AI_HANDOFF pending-commit note differs from the clean Git tree;
actual code/Git were used, and completion state documents were not changed.
Only high-signal current state, direct lifecycle code/tests and relevant architecture
were read; historical TASK-001 through TASK-030 were not rescanned.

Planned scope was app/observability, request middleware/app wiring, Task execution/
pause/recovery, Approval decision, Approved execution/recovery, AgentRuntime,
LLMClient, direct tests, this task document, architecture and a new ADR.

Actual file list:

- backend/app/observability/__init__.py (new)
- backend/app/observability/context.py (new)
- backend/app/observability/events.py (new)
- backend/app/observability/sinks.py (new)
- backend/app/api/request_context.py (new)
- backend/app/main.py
- backend/app/tasks/service.py
- backend/app/tasks/pause_persistence.py
- backend/app/tasks/recovery.py
- backend/app/approvals/service.py
- backend/app/approved_execution.py
- backend/app/executions/recovery.py
- backend/app/agents/runtime.py
- backend/app/llm/client.py
- backend/tests/test_observability.py (new)
- backend/tests/test_observability_lifecycle.py (new)
- docs/ARCHITECTURE.md
- docs/DECISIONS.md (append ADR-009; historical ADRs untouched)
- tasks/TASK-031.md (new)

All writes use repository-relative targets with resolved containment checks.
No migration, dependency or repository-layer instrumentation was necessary.
No existing test required adaptation; new tests are in the two listed test files.

## Architecture / Correlation

ObservabilityEvent defines the stable validated envelope; ObservabilityContext is
a frozen ContextVar snapshot; ObservabilitySink is a minimal protocol. The default
StructuredLoggingSink outputs one JSON line per event through Python logging.
InMemoryObservabilitySink uses locked serialized snapshots for tests. A scoped
use_sink override avoids shared mutable injection state. emit catches construction,
serialization and sink errors; no fallback recursively logs failure payloads.

- request_id: one server-generated UUID per HTTP request/operator invocation.
- task_id: primary business identity across requests.
- thread_id: LangGraph workflow identity, set at Runtime; equal value to Task ID
  today, with explicitly separate semantics.
- approval_id: human authorization identity.
- execution_id: protected Tool execution UUID.
- tool_call_id: LLM ToolCall identity.

HTTP middleware creates a fresh context, ignores client X-Request-ID and returns
its own header even on generated 500 responses. The entire middleware stack is
wrapped so exception handling remains inside the request scope. Nested contexts
and request scopes reset in finally; IDs are not stored in checkpoints/payloads.

## Event Taxonomy

- task.created, task.state_changed, task.completed
- approval.requested, approval.decided
- tool.execution.claimed, tool.execution.cache_hit, tool.execution.succeeded,
  tool.execution.failed, tool.execution.unknown
- workflow.paused, workflow.resumed
- recovery.started, recovery.completed
- llm.request.started, llm.request.succeeded, llm.request.failed, llm.retry.scheduled

18 event names. Start uses task.state_changed PENDING -> RUNNING rather than a
redundant task.started. State transitions include from_status/to_status and emit
only after accepted, acknowledged persistence. Resume events denote authorized
dispatch, not eventual completion. Recovery completion carries the actual result
outcome; unexpected errors record only safe exception type/category.

## Sensitive Data Policy

Allowlisted, constrained scalar metadata only: status transitions, decisions,
model/name/capability, argument_count, attempt/max_attempts/retryable/delay_seconds,
exception_type and fixed error_category. All unknown keys are dropped even when
their names appear harmless. Nested dictionaries and objects never become strings.
Outputs are revalidated against mutation bypasses.

Excluded by default: API keys, Authorization/cookie headers, URLs/credentials,
passwords/tokens, messages/prompts/documents, Tool argument values and keys, Tool
results, model answers, raw checkpoints/HTTP bodies/external responses/exceptions.
Identity/name metadata must remain content-free; do not put user content into an
allowed identifier slot. No automatic PII discovery or arbitrary-payload logger.

## Acceptance Evidence

### Request ID / Full Lifecycle Correlation

A real PostgreSQL/FastAPI test invokes POST /api/agent/run (A), then
POST /api/approvals/{id}/approve (B), with actual AgentRuntime, LLMClient backed
by a fake HTTP transport, durable graph/checkpoints and execution ledger.

Both responses contain UUID X-Request-ID; A != B and the caller-provided header is
ignored. All captured events share the same Task ID. Approval IDs and ToolCall IDs
match durable approval facts; execution events carry the durable execution UUID
and NONE capability. Workflow and LLM events carry the workflow thread identity.
The Tool executes once; Task/ledger finish SUCCEEDED. Key ordering is asserted:
approval.requested before approval.decided, claimed before succeeded/completed.

The ordered Task transitions are PENDING -> RUNNING -> WAITING_APPROVAL -> RUNNING
-> SUCCEEDED. Separate cases cover REJECTED, known FAILED and RECOVERY_REQUIRED.
Parallel overlapping HTTP requests use separate contexts; an unrelated subsequent
request sees no previous Task/Approval/thread/execution identities. Generated 500
responses also carry a UUID and leave no context behind.

### Privacy and best-effort continuity

The complete lifecycle passes distinct sensitive password/api_key/token/email/body
and innocently named values in Tool arguments, a private user prompt, private Tool
result and private LLM answer. Serialized captured events contain none of these
values or credentials. Failure cases also use sensitive exception messages.

A sink that raises on every emit still allows the full protected lifecycle to
commit Approval/Task transitions and execute the Tool once to SUCCEEDED. Separate
broken-sink tests preserve LLM retry/result behavior and successful operator recovery.
Malformed event construction also leaves business code running.

### LLM retry proof

A fake provider returns 503, 429, then a valid 200 response. Attempts are 1, 2, 3
with max_attempts 3; retryable failures and scheduled delays 1.0, 2.0 are captured.
The actual sleep inputs stay [1.0, 2.0], including with a broken sink. A non-retryable
request error produces no retry. Invalid JSON/schema responses emit failed rather
than succeeded and are not retried. No messages, response bodies, URL or keys leak.

### Recovery / transaction proof

Real PostgreSQL cases cover recovery.completed outcomes recovered, no_action,
still_in_progress, recovery_required and orphan_checkpoint with stable Task IDs.
Cached recovery emits tool.execution.cache_hit and keeps Tool count 1. Generation
loss for FAILED/SUCCEEDED/WAITING_APPROVAL emits no false lifecycle commit events.
A real pause rollback emits no committed Approval event and leaves Task RUNNING.
A real SUCCEEDED commit followed by lost acknowledgement emits no unconfirmed
success; fresh recovery emits cache_hit and finishes Task without another Tool call.

## Validation

Temporary PostgreSQL 17 was migrated using existing Alembic 0001-0003 and explicit
LangGraph setup. No external model/provider request and no skipped acceptance test.

- Initial schema/context/request/LLM checks: 15 passed, no failures.
- First focused lifecycle/regression run: 178 passed, 0 failed, 0 skipped, 0 warnings.
- Self-review refined LLM success to follow response validation; two tests ensure
  invalid responses do not produce a misleading success event or a retry.
- Final focused command: `venv/Scripts/python.exe -m pytest tests/test_observability.py tests/test_observability_lifecycle.py tests/test_recovery.py tests/test_execution_ledger.py tests/test_task_resume.py tests/test_hitl_pause.py tests/test_approval_decision.py tests/test_llm_client.py -q`
  Result: 180 passed, 0 failed, 0 skipped, 0 warnings (19.05 seconds).

- Final full PostgreSQL command: `venv/Scripts/python.exe -m pytest -q`
  Result: 417 passed, 0 failed, 0 skipped, 0 warnings (24.54 seconds).
- New TASK-031 coverage: 33 cases (17 schema/context/HTTP/LLM tests and 16 real
  PostgreSQL lifecycle cases). All prior 384 regression tests also pass.

## Remaining Limits / Non-goals

No metrics backend. No distributed tracing backend. No persistent audit log.
Delivery is synchronous and best-effort, with no bounded sink latency, retention,
atomic commit/event delivery or global total order. Telemetry is not an authority
for recovery or authorization; durable business/checkpoint records remain authoritative.
No Prometheus/Grafana/Loki/ELK/Jaeger/Tempo/Datadog/OTel Collector, exporter, alerting,
SLO, dashboard, immutable audit table, distributed propagation or telemetry worker.


## Git / Workspace Audit and Review Handoff

Final actual changes: 11 modified tracked files and 8 untracked files, all listed
above; 0 staged files. git diff --check passed. Resolved containment was verified
for every changed/new file. Historical docs/DECISIONS.md content remains an exact
prefix; only ADR-009 was appended. CURRENT_STATE and AI_HANDOFF have no diff.

All source/document writes used repository-relative paths under the verified root;
no repository-external file creation, modification, moving or deletion was detected.
The dedicated agentflow-task031-test PostgreSQL container and its volumes were
removed after validation. No git add, commit or push was performed.

ADR-009 and TASK-031 remain pending Independent Review. Stop here for review;
implementation/test success does not mark project state Completed.

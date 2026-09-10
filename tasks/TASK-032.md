# TASK-032 - Project Hardening & End-to-End Validation

Status: Developer qualification complete; pending Independent Review.
Functional checks pass. Workspace Boundary Violation occurred during initial
virtual-environment bootstrap; do not interpret test success as overall boundary
or release approval. Docker/CI/deployment qualification gaps remain explicit.

## Workspace / Planned Write Set

Working directory and Git root verified: E:\AIProjects\AgentFlow-AI.
Initial state: main, clean, up to date with origin/main; no staged changes.
Read current state/handoff/roadmap, direct app/services/persistence/observability/
migration/configuration/test wiring; did not rescan TASK-001 through TASK-031.
The handoff pending-commit note was inconsistent with the clean Git working tree;
actual code/Git guided the work, without editing confirmed completion documents.

Planned writes before implementation:

- backend/tests/test_release_e2e.py
- backend/tests/test_migration_qualification.py
- backend/alembic/env.py, conditional on reproduced migration defect
- .env.example
- README.md
- tasks/TASK-032.md
- docs/ARCHITECTURE.md, only the required migration ownership fact
- Ignored repository-local .venv/ for fresh dependency qualification

Added after an E2E failure and announced before editing:

- backend/app/llm/client.py: missing ValidationError import only

Actual tracked/untracked source/document changes are exactly those eight files:
five modified tracked files and three new files. No Runtime subsystem, state
machine, recovery policy, dependency version or historical migration changed.

## Release Qualification Summary

A-G application scenarios pass using real production route/service wiring,
PostgreSQL and PostgresSaver, with a controlled HTTP LLM provider. Fresh application,
Runtime, registry and Saver instances complete HITL and cache/recovery paths without
re-submitting initial input. A separate Uvicorn process also passes live HTTP smoke
with production dependencies and a local controlled provider, without TestClient
or dependency overrides.

These are application qualification results, not unconditional deployment approval.
No Dockerfile/compose application stack or CI workflow exists. Initial bootstrap
violated the repository-only temporary-write guard; the incident is retained below.

## E2E Scenario Results

| Scenario | Verified result |
| --- | --- |
| A Plain Assistant | API 200, final answer persisted, Task SUCCEEDED, one LLM request, zero Tool calls, correlated request/Task events |
| B Safe Tool | Calculator called once, ToolResult 5.0 passed to the second LLM request, no Approval or protected ledger row, Task SUCCEEDED |
| C Protected HITL approve | First app pauses with durable checkpoint/PENDING Approval/WAITING_APPROVAL; fresh app/Runtime/Saver approves and resumes same Task/thread; one authorized Tool invocation/effect; Task/Ledger SUCCEEDED |
| D Protected HITL reject | API and durable Task/Approval REJECTED; zero Tool calls; never conflated with FAILED |
| E Cached replay | Real ledger SUCCEEDED commit followed by lost acknowledgement leaves RUNNING Task/pending tool checkpoint; fresh recovery consumes cache; Tool invocation/effect count before=1, after=1 |
| F1 Dispatch loss | Approval claim commits APPROVED/RUNNING, injected dispatch loss leaves matching pause; stale fresh API recovery completes SUCCEEDED with one Tool call |
| F2 UNKNOWN + NONE | Seeded ambiguous ledger identity remains non-replayable; recovery API returns recovery_required and Task RECOVERY_REQUIRED; zero recovery Tool calls |
| F3 Completed checkpoint | Task final persistence fault leaves RUNNING with END checkpoint; fresh recovery persists final result with zero LLM/Tool calls |
| G Observability | Protected lifecycle event families share task_id; HTTP A/B request IDs differ; Approval/execution/ToolCall IDs match durable facts; private prompt/argument/Tool-result/final-answer values absent from serialized events |

The fresh-runtime test forbids calling AgentRuntime.run on continuation, checks
unchanged checkpoint identity before resume, verifies first/second app and Runtime
objects differ, and confirms none of their Saver objects are shared. The registered
protected test Tool checks persisted APPROVED authorization and RUNNING Task before
recording its effect. No external Tool platform was introduced.

Failure smoke additionally verifies provider failure and invalid ToolCall ID/name
produce safe 502 responses and Task FAILED. Together with D/F2, FAILED, REJECTED and
RECOVERY_REQUIRED retain distinct contracts.

## Clean Database / Migration

Used a dedicated PostgreSQL 17 container, agentflow-task032-test, with a new volume.
The first database reproduced the real mixed-schema Alembic defect before fixing it.
A second initially empty database, agentflow_task032_fresh, qualified the freshly
installed environment from the beginning:

1. Assert database has no tables.
2. alembic upgrade head (0001 -> 0002 -> 0003).
3. python -m app.workflows.setup.
4. Assert all three business tables and four checkpoint tables coexist.
5. alembic check: no new upgrade operations.
6. alembic downgrade base on this disposable database only.
7. Assert business tables removed while checkpoint tables and setup-version history remain.
8. alembic upgrade head, repeat checkpoint setup, then alembic check successfully.

Historical migrations and LangGraph DDL were not rewritten. The fix excludes only
four reflected PostgresSaver-owned tables from business autogeneration. Two negative
PostgreSQL tests prove unexpected business columns and unknown checkpoint_-prefixed
tables still fail check. These temporary test objects are removed in finally.

## Docker Status

Docker CLI and an isolated PostgreSQL container were used for test infrastructure.
The repository itself has no Dockerfile, compose file or application container
support (verified tracked inventory and root contents). Therefore no application
compose down/up/build qualification is claimed, and no containerization subsystem
was added. The dedicated test container/volumes are cleaned after qualification;
unrelated containers were left alone.

## CI Status

CI missing: no .github/workflows files exist. There is no current workflow whose
install/database/migration/test steps can be verified. No CI framework was added.
Local qualification explicitly performed those steps, but it is not a remote CI run.

## Configuration Audit

All eight Settings fields are represented in .env.example with current constraints:
DATABASE_URL, LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT_SECONDS,
LLM_MAX_ATTEMPTS, LLM_RETRY_BASE_DELAY_SECONDS and RECOVERY_STALE_AFTER_SECONDS.
No real secret was printed or committed. Settings reads repository-root .env with
process-environment overrides. Existing TD-005 remains: Alembic loads shared LLM
settings, so harmless placeholder LLM fields are needed for isolated migrations.

README now explains Python 3.11/PostgreSQL 17 prerequisites, guarded fresh venv,
installation/pip check, .env setup, separate business/checkpoint initialization,
backend working directory, Uvicorn, API smoke and disposable test database use.
The old TASK-001-only status/stack description was stale and was corrected without
marking CURRENT_STATE or AI_HANDOFF complete. LANGSMITH_TRACING=false was set only
in qualification processes; no new Settings field or telemetry backend was added.

## Dependency Audit

Existing environment: python -m pip check -> No broken requirements found.
Created a new repository-local .venv and installed backend/requirements.txt from
scratch with --no-cache-dir. One PyPI connection timeout was retried successfully.
All 55 explicitly pinned versions match installed metadata; fresh pip check also
reports no broken requirements. No major upgrade or speculative dependency removal.
Final migrations, high-risk regressions, full suite and Uvicorn smoke use this new
environment. Temporary directories for installation/testing were redirected into
.venv/tmp after the initial bootstrap incident described below.

## API Smoke Test

Real route wiring covers /api/health, POST /api/agent/run, GET /api/tasks,
GET /api/tasks/{id}, Approval approve/reject and POST /api/tasks/{id}/recover.
A live subprocess running uvicorn app.main:app passes health, Agent run and Task
query/list over real HTTP sockets with no dependency overrides. Its structured
JSON records share the response request ID and Task ID and exclude private values.
The controlled provider receives exactly one request in the live plain-assistant
case. The server and provider are closed by the test.

## Bugs Found and Fixed

- IMPORTANT: Alembic interpreted four PostgresSaver tables/indexes as pending
  removals after setup. Reproduced check failure; fixed the explicit ownership
  filter. Business drift detection remains tested and intact.
- IMPORTANT: Empty provider ToolCall ID/name caused NameError because the parser's
  ValidationError handler lacked its import, giving API 500 instead of safe 502.
  Reproduced in E2E; added one import and covered both malformed fields.
- IMPORTANT: Workspace Boundary Violation in initial venv bootstrap and system-temp
  probing. Mitigation and corrected bootstrap verification are recorded below;
  this is not erased or treated as boundary PASS.
- NOTE: Docker application support and CI are missing; no unrequested DevOps work.
- NOTE: README/configuration explanations were stale/incomplete; corrected within
  existing features. Existing shared migration Settings coupling remains TD-005.

No new blocking application defect remains in the exercised paths. This statement
does not waive process incidents or substitute for independent release review.

## Tests

All final runs use real PostgreSQL; no core E2E was skipped.

| Run | Passed | Failed | Skipped | Warnings | Duration |
| --- | ---: | ---: | ---: | ---: | --- |
| Initial TASK-032 focused, before parser fix | 12 | 1 | 0 | 0 | 7.33s |
| TASK-032 E2E + migration focused, fresh venv | 15 | 0 | 0 | 0 | 10.32s |
| TASK-032 + TASK-028-031 high-risk integration | 138 | 0 | 0 | 0 | 25.37s |
| Full PostgreSQL suite, fresh venv/database | 432 | 0 | 0 | 0 | 33.29s |

Commands from backend (interpreter ../.venv/Scripts/python.exe):

- -m pytest tests/test_release_e2e.py tests/test_migration_qualification.py -q
- -m pytest tests/test_release_e2e.py tests/test_migration_qualification.py tests/test_task_resume.py tests/test_execution_ledger.py tests/test_recovery.py tests/test_observability.py tests/test_observability_lifecycle.py -q
- -m pytest -q

The initial failing test was retained and fixed through the production import;
no test deletion, weakening or hidden skip. New coverage totals 15 cases: 12 E2E/
live HTTP cases and 3 migration/schema-drift cases, in addition to the previous 417.
Pip's recovered connection-timeout warning is separate from pytest warning counts.

## Workspace Boundary Verification / Incident

Workspace Boundary Violation occurred. Before the initial python -m venv .venv,
TEMP/TMP had not been redirected. Python ensurepip uses TemporaryDirectory and
copies bundled installation wheels there; the inherited default resolved to
C:\WINDOWS\TEMP. The later tempfile.gettempdir probe also uses transient directory
validation files. Those transient files are automatically cleaned by the successful
library operations. This conclusion is based on the executed bootstrap, inherited
temporary directory and inspected standard-library implementation, not a retained
per-file OS audit trace. No manual repository-external cleanup was performed.

No other project's source/document files were observed modified. All explicit
source/document targets were repository-relative and containment checked. Once
identified, installation/testing used repository-local .venv/tmp. A separate clean
bootstrap into .venv/bootstrap-verification was then run with TEMP/TMP containment
asserted before creation and passed (pip installed inside that venv). README now
sets TEMP/TMP before bootstrap. This verifies the corrected procedure but does not
retroactively remove the earlier violation or permit an overall boundary PASS.

## Remaining Release Gaps / Producer Decisions Required

- Decide whether Docker application packaging and CI are release gates and should
  be assigned independent closing tasks; both are absent today.
- Define the target deployment/environment acceptance if a deployed release is
  required. Qualification uses a controlled provider, not production credentials.
- Independent Review must explicitly assess the recorded workspace incident;
  functional green tests alone must not close that review finding.

No new Agent feature, Runtime subsystem, recovery policy, queue/worker/scheduler,
MCP/multi-agent, frontend, metrics/tracing backend or persistent audit was added.

## Git Audit / Review Handoff

Final git diff --check passed. The dedicated PostgreSQL container and both temporary
databases/volume were removed; unrelated containers were left untouched.
No git add, commit or push. No staged changes. CURRENT_STATE and AI_HANDOFF remain
unchanged. Source/document write set: five tracked modifications and three untracked
files (eight total); ignored .venv artifacts are local qualification environments.
Stop for Independent Review; no project-state completion is asserted.

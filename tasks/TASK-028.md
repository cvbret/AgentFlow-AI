# TASK-028 - Approved Tool Resume Integration

Status: Developer implementation; pending Independent Review.

## Workspace / Planned Write Set

Root and working directory: E:\AIProjects\AgentFlow-AI.
Branch: main. Initial status: clean, up to date with origin/main.
All source/document writes use contained repository-relative paths.

Planned and actual files:

- backend/app/agents/runtime.py
- backend/app/workflows/agent.py
- backend/app/workflows/graph.py
- backend/app/approved_execution.py (new)
- backend/app/approvals/continuation_persistence.py (new)
- backend/app/approvals/service.py
- backend/app/tasks/models.py
- backend/app/tasks/repository.py
- backend/app/tasks/service.py
- backend/app/tasks/resume.py (new)
- backend/app/api/dependencies.py
- backend/tests/test_workflow.py
- backend/tests/test_approval_decision.py
- backend/tests/test_approval_rejection.py
- backend/tests/test_task_resume.py (new)
- docs/ARCHITECTURE.md
- docs/DECISIONS.md (append ADR-006; ADR-005 unchanged)
- tasks/TASK-028.md (new)

## Pause Architecture / Durable State

Real application Runtime uses TASK-026 PostgresSaver, opening/closing a saver per
invoke, compiled graph per invoke and Task.id as configurable.thread_id.
Graph invoke explicitly requests synchronous checkpoint durability.

Tool processing catches ApprovalRequired and RETURNS completed messages,
tool_calls/tool_cursor and the original Approval JSON snapshot. A separate
approval_pause node invokes interrupt with no pre-interrupt business side effects.
Resume therefore replays the pause node, not completed tool processing.

State consists of JSON-compatible task identity, message snapshots, ordered call
snapshots/cursor, pending Approval correlation/context, resume correlation,
step_count, original max_steps and final answer. Foundation-only resume_result
remains optional. No Session, Repository, client, Tool, service or connection is
stored. Approval snapshot is not decision authority. AgentFlow ChatMessage and
ToolCall are reconstructed at existing boundaries, without LangChain messages.

## Checkpoint / Business Ordering

Runtime exposes ApprovalRequired only after durable interrupt/checkpoint success,
using the original Approval ID and ToolCall context. Existing HITLPausePersistence
then atomically writes PENDING Approval + WAITING_APPROVAL Task.
Checkpoint failure never exposes business pause. A business pause failure after
checkpoint can leave an orphan checkpoint, while existing conditional failure
handling applies and no protected tool executes. Orphan cleanup is deferred.

## Approval Continuation Claim / Resume Service

Task.resume_approved adds WAITING_APPROVAL -> RUNNING.
ApprovalContinuationPersistence conditionally updates Approval PENDING -> APPROVED
and Task WAITING_APPROVAL -> RUNNING in one short transaction. Approval-first,
Task-second order matches rejection. False updates or exceptions roll back both.
Only the winning decision dispatches TaskResumeService after commit.

TaskResumeService reads an existing RUNNING Task, ends the read transaction, then
calls Runtime.resume. Shared TaskExecutionService handling persists SUCCEEDED,
conditional FAILED or a new Approval/WAITING_APPROVAL. No transaction crosses
Graph, LLM or Tool execution. Reject remains non-executing.

## Authorization / Compatibility

Runtime validates durable task/thread/approval correlation before Command(resume).
ApprovedToolExecutionService rereads persisted Approval and verifies APPROVED,
approval ID, task ID, tool_call_id, tool name and exact JSON arguments before
resolving the Tool and reusing Tool.execute validation/results/errors.
No bool authorization, force or skip-policy flag exists.

Original LLM round count and max_steps survive fresh runtime construction. Last
allowed round executes its tools before exhaustion; final answers remain valid
at the boundary. Runtime without a saver retains standalone non-durable behavior
for compatibility/unit use; real API wiring uses PostgreSQL and cannot resume
without it. Checkpoint setup remains an explicit deployment step.

Approval API successful response DTO is unchanged. Approve synchronously invokes
continuation through an application service; Task Query exposes the result.
Continuation failures propagate after the decision commits, following existing
failure persistence/error handling; repeated decisions conflict rather than retry
execution. This does not reconcile lost commit acknowledgements.

## Acceptance Evidence

`tests/test_task_resume.py` covers:

- Real PostgreSQL Runtime A pause, durable state inspection, A.close and disposal,
  then fresh Runtime B / compiled graph / saver, same Task.id, no initial input
  resubmission, approved continuation and Task SUCCEEDED. This is fresh-runtime
  proof, not a claim of a new OS-process crash test.
- PENDING/WAITING visible from an observer before the claim commit; both updated
  values visible inside the transaction; exactly one claim commit, RUNNING after
  commit, graph execution afterward.
- Safe A / protected B / safe C: initial counts (1, 0, 0), final counts (1, 1, 1).
  Saved cursor and ordered tool messages verified; A does not replay.
- Second protected call creates a distinct PENDING Approval and WAITING Task,
  followed by a second approved continuation.
- Real API start/pause, fresh runtime approve, unchanged DTO, query SUCCEEDED,
  repeat approve conflict without another tool call.
- Real PostgreSQL approve/approve and approve/reject races: one winner, at most
  one resume callback and one normal-path protected execution.
- Task-update and deferred-commit trigger failures roll back Approval and Task;
  continuation callback never runs.
- Checkpoint success/business pause failure retains an orphan and no protected
  effect; checkpoint write failure never invokes business pause.
- Wrong task/approval, missing/PENDING/REJECTED Approval and mismatched call/name/
  arguments fail closed. Raw boolean and correlated-but-unapproved Command
  payloads cannot authorize protected execution.
- Resume LLM/input/Tool/budget failure persists FAILED via existing contract.
  Original budget is retained despite a fresh runtime's different default.

Existing Runtime/HITL and approval regression tests are reused. Decision tests
now expect RUNNING after a claim, or SUCCEEDED after mocked API continuation;
real durable API behavior is separately covered above.

## Validation

Final synchronous-durability validation:

- Focused: `venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_workflow.py tests/test_hitl_pause.py tests/test_approval_decision.py tests/test_approval_rejection.py tests/test_task_resume.py -q`
  — 91 passed, 0 failed, 0 skipped, 0 warnings (12.76 seconds).
- Full: `venv/Scripts/python.exe -m pytest -q`
  — 318 passed, 0 failed, 0 skipped, 0 warnings (18.96 seconds).
- New resume suite contributes 25 cases: 24 real PostgreSQL cases plus one Domain
  case, included in both runs above. Existing concurrency/rollback regressions
  also execute against PostgreSQL.
- During development the new API proof initially used `input` instead of the
  existing request field `message` and returned 422; the test request was corrected.
  The final focused/full runs above passed without changing the API contract.
- `git diff --check` passed. No staged changes; all 18 changed/new files belong to
  the planned scope. No repository-external source/document writes occurred.
A temporary PostgreSQL 17 database is used for focused and full regression;
Alembic business migrations and explicit workflow setup initialize it. No live
provider calls are used. No acceptance integration tests are intentionally skipped.

## Remaining Crash Windows / Non-goals

No crash-safe exactly-once yet. External side effect success followed by a crash
before durable tool-node progress or Task completion may replay under future
recovery. A committed RUNNING claim can remain stale if dispatch/process fails.
Checkpoint/business commits are separate; orphan checkpoints, stale RUNNING,
lost acknowledgements and cross-store reconciliation are deliberately unresolved.
TASK-029: ledger/idempotency/duplicate prevention. Later recovery/reconciliation
(TASK-030 scope to be defined) requires separate design.

No ledger, idempotency framework, automatic resume, queue, worker, distributed
execution, parallel approvals, multi-agent, MCP or orphan cleanup is implemented.
CURRENT_STATE and AI_HANDOFF are unchanged; no project completion declaration.
No add/commit/push. Stop for Independent Review.

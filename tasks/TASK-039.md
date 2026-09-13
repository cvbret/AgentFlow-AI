# TASK-039 - Tool Permission Enforcement

Status: Completed. Independent Re-Review #2: PASS WITH NOTES.
BLOCKER = 0; IMPORTANT = 0; original IMPORTANTs = Closed. Awaiting Human Gate.
The implementation and validation entries below are historical snapshots; final status supersedes their pending-review statements. Prior TASK-038 documentation edits are preserved.
Scope: exact AgentToolPolicy allow-list enforcement inside existing Tool boundaries;
no Runtime/graph/Approval/Ledger/recovery lifecycle redesign, enterprise authorization,
new executor, RBAC, OAuth, policy DB or telemetry pipeline.

Planned Write Set: backend/app/tools/permission.py, exceptions.py, executor.py, base.py;
backend/app/protected_execution.py, approved_execution.py; agents/supervisor.py,
agents/policy.py; observability/events.py; focused permission tests; this task record;
docs/ARCHITECTURE.md, CURRENT_STATE.md, AI_HANDOFF.md, ROADMAP.md, DECISIONS.md.
Temp/test evidence stays in .venv/tmp/task039 with repo-local TEMP/TMP.


## Actual implementation

Added scoped identity and a single AgentToolPolicy decision helper in tools/permission.py.
Existing ToolExecutor, ProtectedToolExecutionService, ApprovedToolExecutionService.validate
and Tool.execute guard their entry boundaries. No new Executor/Runtime. Supervisor
binds selected Worker identity only; Runtime and graph source are unchanged. Inherited
recovery uses the existing validate call, so no recovery/ledger lifecycle edit is needed.
Added ToolPermissionDenied and tool.permission.denied via existing safe event emission.

Tests: new test_tool_permissions.py (24 cases), one new Supervisor import-boundary
case and a narrow update to the existing AST boundary test permitting only the
identity context import. All other execution imports/loops remain prohibited. This
reflects identity transport, not moving permission logic into Supervisor.

## Evidence

Focused command (backend):
python -m scripts.qualified_tests -q tests/test_tool_permissions.py tests/test_supervisor.py
Result: 39 passed / 0 failed / 0 skipped / 0 warnings (2.57 s).

Regression command (backend, dedicated PostgreSQL 17):
python -m scripts.qualified_tests -q tests/test_tool_permissions.py tests/test_supervisor.py tests/test_tools.py tests/test_tool_calling.py tests/test_protected_execution.py tests/test_agent_runtime.py tests/test_agent_abstraction.py tests/test_observability.py tests/test_execution_ledger.py tests/test_task_resume.py tests/test_recovery.py
Result: 245 passed / 0 failed / 0 skipped / 0 warnings (26.41 s).
39 is a subset of 245. No full historical suite or real LLM/provider verification repeated.
Used the existing Compose PostgreSQL definition with an isolated task039 project,
a repo-local random loopback port override and fake provider configuration. Existing
Alembic upgrade and PostgresSaver setup passed. No application database was used.

Checks cover allowed/denied, no approval for denied Tool, allowed still requires HITL,
Supervisor no privilege bypass, selected Worker grants, real LangGraph ToolCall paths,
no ledger/approval/cache access on deny, successful ledger replay effect count one,
context nesting/exception cleanup/concurrent isolation, no payload telemetry, and
broken sink still denies. No permission decision in AgentRuntime or LangGraph.

## Boundaries / future extension

See ADR-013. No Enterprise Authorization, Dynamic Policy, User-level Permission,
RBAC, OAuth, Policy DB, new permission approval workflow or telemetry pipeline.
Trusted Agent context is required for Agent enforcement; old non-Agent calls remain
compatible. The initial non-durable implementation was rejected for fail-open
continuation; the focused fix below supersedes that boundary.
This task does not add full multi-agent resume, policy versioning,
public API Agent authentication or malicious-Python-code sandboxing.

## Workspace / documentation

Verified E:\AIProjects\AgentFlow-AI before writes, repository-relative writes and
resolved containment used. TEMP/TMP and Docker client state are under .venv/tmp/task039.
Four docs had existing user changes (CURRENT_STATE, AI_HANDOFF, ARCHITECTURE, ROADMAP);
none were reverted. Updated current TASK-039 status as Developer implementation complete
with Independent Review pending rather than fabricating a completed review. Historical
ADR-012 proposal status and TASK-038 review snapshot differ; ADR history was not rewritten.
No add/commit/push. No source changes to AgentRuntime, LangGraph, Approval flows,
Ledger lifecycle or recovery mechanism; only the existing Tool validation entry gains
the permission guard. No .env or dependency changes.

Final audit: git diff --check passed; staged diff empty. Runtime, workflow,
Approval and executions module diffs are empty, as is requirements.txt. The added
Supervisor test file is included in the actual write set. Dedicated task039 test
container/network stopped and removed using compose down without -v; its volume
was retained. No application/user database or .env was modified. No repository-
external host file writes detected; this is process evidence, not OS sandboxing.


## TASK-039 Focused Fix — Identity continuity / Awaiting Re-Review

Reviewer confirmed IMPORTANT: a paused Agent-bound workflow lost its transient
ContextVar on resume and silently took the unrestricted legacy branch. The fix is
implemented and awaits Independent Re-Review; this is not Review Passed.

Runtime.run now records only execution_mode (LEGACY / AGENT_BOUND) and
agent_identity (Agent.name or null) in existing workflow checkpoint state.
These fields originate from the trusted invocation context, never user messages,
AgentMessage metadata, LLM output or Tool arguments. No Agent object, grants,
prompt or policy snapshot is persisted; no business table or migration is added.

Normal resume and resume_pending_tool restore provenance before continuation.
Runtime assembles ApprovedToolExecutionService / ExecutionRecoveryService with
the same task-scoped provenance callback, covering validation, cache replay,
claims and recovery effects, including direct calls to these Runtime-owned services.
Permission decisions remain at existing Tool boundaries, before persisted Approval
reads and Ledger/cache/claim/effect access. Existing claim/fencing/error contracts
and safety checks are preserved.

Restoration uses injected agent_loader(name), supplied by trusted application
composition (for example AgentRegistry.get). The returned Agent must match the
persisted name. Missing resolver, unresolved/mismatched identity, malformed mode,
missing identity on AGENT_BOUND, missing checkpoint or mismatched task fail closed
with an authorization error (or resolver failure). A conflicting ambient Agent
cannot override provenance; even a same-name ambient Agent cannot substitute its
grants for the trusted loader's policy. ContextVar is now only transient transport
for the restored Agent, always reset when continuation exits or raises.

Second Focused Fix supersedes the initial compatibility interpretation:
only explicit LEGACY checkpoints retain legacy continuation. Missing/null/unknown
mode is ambiguous and rejected; new non-Agent runs explicitly store LEGACY.
Standalone non-workflow Approved/Recovery services retain their legacy constructor
contract; trusted composition must use the provenance callback for workflow-owned
operations. They are not public Agent authorization endpoints.

Configuration/rollout: agent_loader is optional for backward compatibility; existing
application factories without it deliberately cannot resume AGENT_BOUND workflows.
Wire the trusted AgentRegistry loader before enabling their successful continuation.
Name reuse must not assign an old identity to a different principal. This fix does
not add policy versioning, message persistence or delegation-result reconstruction.
Pre-fix checkpoints that never recorded Agent provenance cannot be distinguished
retrospectively from true legacy records: ALL ambiguous historical continuations
are now rejected. Trusted migration/state repair must establish provenance before
resuming; manual isolation alone does not authorize continuation.
Arbitrary tampering with trusted checkpoint storage/Python internals is outside this
trust boundary; external payloads cannot set the provenance fields.

Verification on isolated task039 PostgreSQL:
- Focused (identity + TASK-039 permission + Supervisor): 57 passed, 0 failed,
  0 skipped, 0 warnings.
- Affected set (above plus task resume, execution ledger, recovery and approval
  decision): 160 passed, 0 failed, 0 skipped, 0 warnings.
57 is a subset of 160; counts are not additive. No historical full qualification,
Docker qualification, hosted CI or real provider test was repeated.


## TASK-039 Second Focused Fix — Awaiting Independent Re-Review

第一轮将 missing mode 视为 LEGACY，仍可能放行修复前的 Agent-bound checkpoint。
本轮修正现有 Runtime provenance 判定，保留原有 Agent loader 与 Tool policy 链路：

- 显式 LEGACY 且无 Agent identity：保持 legacy continuation。
- 显式 AGENT_BOUND：继续从可信 loader 恢复 Agent；身份异常仍 fail closed。
- execution_mode 缺失、null 或未知：以 ResumeAuthorizationError 拒绝，
  错误说明 continuation provenance 无法确认。不得依据 ambient ContextVar、
  caller 参数或外部 payload 猜测 legacy，未提供 legacy=True 绕过入口。

Missing provenance is not legacy. Ambiguous historical continuation fails closed.
Only explicit LEGACY state receives legacy compatibility.
所有新 Runtime.run 已显式写入 LEGACY / AGENT_BOUND；本轮未改变初始执行协议。
未知历史状态需要可信迁移/修复确认来源，才可继续；可先人工隔离，未实现通用迁移工具。

修改范围：backend/app/agents/runtime.py、backend/tests/test_agent_identity_continuity.py，
以及 tasks/TASK-039.md、CURRENT_STATE、ARCHITECTURE、AI_HANDOFF、DECISIONS。
未修改第一轮其他身份装配与权限执行代码，未新增依赖/数据库/Runtime。

新增回归在初始 checkpoint 写入前移除两个 provenance 字段，复现旧格式的
Agent-bound protected → safe 流程，经真实 PostgreSQL pause/approve 后 fresh Runtime
恢复。覆盖 absent/null/unknown mode 的 resume、pending tool、Approved、Recovery，
确认 loader 不被用来猜测身份，Approval/Ledger 未访问，Tool effect 为零。
另验证已有 SUCCEEDED cache 不能绕过拒绝，以及显式 LEGACY recovery 可复用结果。

本轮最终验证：
- Focused（identity continuity + permission + Supervisor + Runtime direct）：
  93 passed / 0 failed / 0 skipped / 0 warnings。
- Affected PostgreSQL（包含上述集合及 Approval/Task resume/Ledger/Recovery）：
  196 passed / 0 failed / 0 skipped / 0 warnings。
93 是 196 子集，不累加；前轮 57/160 属于历史记录。
首次命令未设置 DATABASE_URL，出现 32 skipped，被 qualification gate 拒绝；
显式配置独立 task039 PostgreSQL 后完成上述零跳过验证。
未重复 Docker/CI/真实 Provider/全历史 qualification。git diff --check 通过。

## Complete Review History

1. Initial implementation: scoped exact allow-list checks at existing Tool boundaries;
   Developer evidence 39 focused / 245 affected PostgreSQL passed (historical).
2. Initial Independent Review → **NEED FIX**: IMPORTANT #1, pause/resume lost
   transient ContextVar identity and could degrade to unrestricted legacy execution.
3. Focused Fix #1: durable execution_mode / agent_identity, trusted agent_loader,
   continuation restoration. Historical Developer evidence: 57 / 160 passed.
4. Independent Re-Review #1 → **NEED FIX**: IMPORTANT #2, historical checkpoints
   without provenance could still be automatically interpreted as LEGACY.
5. Focused Fix #2: missing/null/unknown or inconsistent provenance fails closed;
   compatibility requires explicit LEGACY. Developer evidence: 93 / 196 passed.
6. Independent Re-Review #2 → **PASS WITH NOTES**: Reviewer independently confirmed
   196 passed / 0 failed / 0 skipped / 0 warnings plus ambiguous-checkpoint probe.
7. Original IMPORTANT #1 → **Closed** by durable trusted identity continuity;
   original IMPORTANT #2 → **Closed** by explicit three-state fail-closed semantics.
   BLOCKER: None. IMPORTANT: None. Only NOTE: trusted historical checkpoint migration.

## TASK-039 Final State — Completed / PASS WITH NOTES

Independent Re-Review #2: **PASS WITH NOTES**. BLOCKER = 0; IMPORTANT = 0;
both original IMPORTANTs = **Closed**. State Synchronization complete; awaiting Human Gate.
Review evidence is supplied by TASK-039_State_Synchronization_Developer_Prompt.md:
Independent Reviewer personally ran the affected PostgreSQL regression and confirmed
**196 passed / 0 failed / 0 skipped / 0 warnings**. This documentation-only round
has not rerun those tests. Coverage includes historical missing/null/unknown provenance,
explicit LEGACY/AGENT_BOUND, fresh Runtime/Saver continuation, permissions, Supervisor,
Approval, Ledger and Recovery. Reviewer probe: Tool effects = 0, Ledger calls = 0,
loader calls = 0, and no successful result for an ambiguous historical checkpoint.

AgentToolPolicy is enforced as an exact allow-list at the real Tool Runtime boundary,
before Approval reads, Ledger claims, cached-result reuse or Tool effects.
ToolPermissionDenied is not converted into an ordinary Tool execution failure.
Supervisor/Runtime transport trusted Agent identity; LLM output, Tool arguments,
AgentMessage metadata and ordinary external payloads cannot override it.
Runtime persists execution_mode and agent_identity in existing LangGraph checkpoints,
restores trusted identity through agent_loader on continuation, and binds transient
execution context. Runtime does not make Tool permission decisions; ContextVar is
transport only, never the sole durable identity source.

| Continuation provenance | Final behavior |
| --- | --- |
| Explicit LEGACY, no Agent identity | Explicit legacy compatibility |
| Explicit AGENT_BOUND | Restore durable trusted Agent identity and enforce AgentToolPolicy |
| UNKNOWN / missing / null / unknown value / inconsistent mode and identity | Fail closed via ResumeAuthorizationError; no unrestricted continuation |

The only TASK-039 Reviewer NOTE is Historical Ambiguous Checkpoint Migration:
historical checkpoints without trustworthy provenance are rejected by default.
Continuation requires trusted source verification and migration to explicit LEGACY
or AGENT_BOUND first. General migration tooling is not implemented. This is a
compatibility boundary of safe fail-closed behavior, not an open TASK-039 defect.

Completed Multi-Agent capabilities: TASK-035 architecture research (research deliverable),
TASK-036 Agent Abstraction, TASK-037 Communication Contract, TASK-038 Supervisor
Orchestration, TASK-039 Tool Permission Enforcement. TASK-035 research completion
does not imply acceptance of the separately Proposed ADR-011.

Not completed: Multi-Agent HITL Integration, full/advanced delegation recovery
semantics and result reconstruction, historical provenance migration tooling,
Planner, dynamic routing, scheduling, and message persistence.

Next task: **TASK-040 - Multi-Agent HITL Integration**. Status: **Not Started**.

## State Synchronization — Documentation-only delivery

Planned Write Set / Actual files updated:
- docs/CURRENT_STATE.md
- docs/ARCHITECTURE.md
- docs/AI_HANDOFF.md
- docs/ROADMAP.md
- docs/DECISIONS.md
- tasks/TASK-039.md

Resolved stale pending-review snapshots against the supplied final Reviewer outcome
and inspected Runtime/Tool source and identity-continuity tests. Earlier implementation
and review evidence above is retained as history. ADR-013 records the reviewed
implementation without automatically becoming Accepted; unrelated ADR statuses remain.
No business code or tests changed in this synchronization; no tests rerun.
Reviewer results above are attributed evidence, not this round's test execution.
Working directory and Git root verified as E:\AIProjects\AgentFlow-AI;
repository-relative writes used with resolved containment checks. Existing tracked
and untracked implementation/test changes were preserved; no staged changes.
No repository-external writes, creations, moves or deletions. No add, commit or push.
State Synchronization awaits Human Gate; TASK-040 remains Not Started.

Synchronization validation: git diff --check passed (exit 0); existing backend LF/CRLF
normalization notices are Git notices, not test warnings. Git status: 17 tracked
modified files (12 pre-existing backend source/test files plus five updated docs),
4 untracked files (three pre-existing backend source/tests plus tasks/TASK-039.md),
and no staged files. All files outside the six-document write set were verified
unchanged by SHA-256 before/after comparison. No new technical debt introduced;
the historical migration NOTE remains the explicitly documented compatibility limit.

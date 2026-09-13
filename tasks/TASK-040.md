# TASK-040 — Multi-Agent HITL Integration

Status: **Completed**
Implementation Complete. Independent Review: **PASS WITH NOTES**.
BLOCKER: 0. IMPORTANT: 0. NOTE: independent read Session contract.
State Synchronization complete; awaiting Human Gate.

## Objective

Supervisor 委派 Worker 调用 protected Tool 时复用现有 durable HITL；approve 后
fresh Runtime 恢复原 Worker identity 并复查 Tool policy；reject 保持 REJECTED。
无新的 Runtime、Approval/Recovery 状态机、graph、表、migration 或消息持久化。

## Developer Implementation — Planned Write Set / Actual Files Changed

计划与实际一致，共 10 个文件；7 个 tracked 修改、3 个新增文件，未 staged。

- backend/app/agents/supervisor.py
- backend/app/tasks/service.py
- backend/app/tasks/delegation.py (new)
- backend/tests/test_multi_agent_hitl.py (new)
- tasks/TASK-040.md (new)
- docs/CURRENT_STATE.md
- docs/ARCHITECTURE.md
- docs/AI_HANDOFF.md
- docs/ROADMAP.md
- docs/DECISIONS.md (ADR-014, Proposed)

## Integration / Ownership

`execute_delegated_task(service, supervisor=..., registry=..., task_input=...)`
返回 `(Task, original_request)`，包括 WAITING_APPROVAL 情况。TaskExecutionService
可选 trusted invoke hook 使用同一 continue_running 异常/pause/result 持久化路径。
Supervisor 的 on_request callback 仅暴露 REQUEST 副本，不处理 ApprovalRequired。

调用方使用现有 ApprovalDecisionService + TaskResumeService 决策与恢复；注入配置
trusted agent_loader 的 fresh Runtime/checkpointer，无需手工恢复 ContextVar。
随后用独立只读 Session 调用
`read_delegation_result(original_request, session=session, runtime=fresh_runtime)`。
该函数结束读取 transaction 后读取 checkpoint；不要传入含待提交写入的 Session。

Result reader 校验 Task id/input、AGENT_BOUND、Worker identity；成功结果还要求
terminal checkpoint 的 final_answer 与 Task.result 一致。等待返回 None；成功返回
Worker → Supervisor RESULT；REJECTED/FAILED 返回带原 TaskStatus 的 ERROR。
`in_reply_to` 始终关联原 REQUEST。此内部接口只投影结果，无执行、审批或认证能力。
调用方仍负责 Runtime/Session 资源与 REQUEST retention；不提供 HTTP endpoint。

## Authorization vs Approval / Ledger / Recovery

Worker identity → AgentToolPolicy → protected Tool HITL → human decision →
checkpoint provenance + trusted agent_loader → current policy → existing approved
execution → Ledger/cache/claim/idempotency → effect。Human Approval 不提升权限。
未授权请求在 Approval/Ledger 之前拒绝；Supervisor grants 不继承给 Worker。
权限在等待期间收紧后，即使 Approval 已提交 APPROVED，执行仍被拒绝；沿现有
Task service 记录 FAILED，无 Tool effect。reject 原子记录 REJECTED，不执行或重试。

未修改 AgentRuntime、LangGraph、Approval、Ledger、Tool Runtime 或 Recovery。
缓存重复读取不新 claim，execution UUID/idempotency key 保持，副作用计数为 1。
既有 Recovery 处理 approval dispatch loss 和 succeeded Ledger / lost workflow
progress；身份与权限仍由 TASK-039 provenance 边界保护。无通用 crash-safe
exactly-once 声明，UNKNOWN 等能力边界仍按原 Ledger/idempotency 实现。

## Developer Tests Added / Verification Results

真实 PostgreSQL，独立 compose project `task040`，全新 volume，执行现有 migrations
及 PostgresSaver setup。Mock LLM 与计数 protected calculator 只代替外部服务；
Task、Approval、Ledger、checkpoint 均为真实数据库路径。

Focused：**7 passed / 0 failed / 0 skipped / 0 warnings**（3.99s）。
Affected regression：**183 passed / 0 failed / 0 skipped / 0 warnings**（52.29s）。
Focused 是后者子集，不相加。运行 qualified_tests gate，未运行历史全量资格验收、
CI、Docker qualification 或真实 Provider E2E。

```powershell
# backend working directory; DATABASE_URL points to isolated task040 PostgreSQL.
../.venv/Scripts/python.exe -B -m scripts.qualified_tests -p no:cacheprovider -q tests/test_multi_agent_hitl.py
../.venv/Scripts/python.exe -B -m scripts.qualified_tests -p no:cacheprovider -q tests/test_multi_agent_hitl.py tests/test_supervisor.py tests/test_agent_identity_continuity.py tests/test_tool_permissions.py tests/test_task_execution_integration.py tests/test_task_resume.py tests/test_approval_decision.py tests/test_execution_ledger.py tests/test_recovery.py
```

新增覆盖：

1. Approve fresh Runtime/Saver，原 Worker effect identity、RESULT correlation、单 Approval/Ledger、稳定 UUID/key、缓存无新 claim、重复 decision 冲突。
2. Reject 保持 REJECTED，ERROR 上传状态，无 Ledger、Tool effect 或 LLM retry。
3. 无权限 Worker 不继承 Supervisor grants，不创建 Approval/Ledger。
4. 等待后权限收紧；APPROVED 不绕过 current policy，无 effect。
5. 既有 Recovery 恢复 approval dispatch loss，结果正确关联 Supervisor。
6. succeeded Ledger 尚未推进 graph 的 stale recovery 使用缓存，effect 仍为 1。
7. 无 Tool 的直接完成、waiting None、错误 request kind/content/identity fail closed。

既有受影响测试继续覆盖 missing/unknown provenance、ambient identity、cache policy、
legacy explicit mode、Approval 原子性、ledger replay 和 recovery 边界。

开发中修正了测试的两个调用签名错误；新增缓存恢复场景首轮未将新 Ledger 变旧，
触发 STILL_IN_PROGRESS。已正确模拟 stale Ledger，未弱化生产 live-owner 保护。
最终上述两组验证均为零失败。

## Known Limitations / Technical Debt

- 无 rejection 后 re-plan、fallback Agent、多人工审批或 Agent-to-Agent approval。
- REQUEST 由可信 application caller 保留；fresh Runtime/Saver 支持恢复，但调用方
  丢失 REQUEST 后不能重建原 message correlation。本任务明确不实现消息存储。
- 结果读取是 projection；重复读取可生成新的 message_id，不是 exactly-once delivery。
- trusted invoke hook/agent_loader 由应用组合，非用户身份认证或 OS sandbox。
- 未引入新的基础设施或重试策略；保留既有 UNKNOWN-effect 与历史 provenance migration 边界。

## Workspace Boundary Verification / Review Readiness

Repository root / working directory verified: `E:\AIProjects\AgentFlow-AI`。
使用 repository-relative 写入并验证 containment。未发现 repository root 之外的写操作；
未在仓库外创建、修改、移动或删除文件。独立测试 PostgreSQL 关闭时保留 volume。
未 git add / commit / push。`git diff --check` 须在交付前通过。

Historical Developer delivery status: Implementation complete / Awaiting Independent
Review. This prior checkpoint is superseded by the final Independent Review below.

## Independent Review — Final Evidence

Independent Review: **PASS WITH NOTES**; BLOCKER = 0; IMPORTANT = 0.
Reviewer allowed State Synchronization. Per the supplied
TASK-040_State_Synchronization_Developer_Prompt.md, the Independent Reviewer
personally executed **183 passed / 0 failed / 0 skipped / 0 warnings** using fresh
PostgreSQL 17, Alembic and PostgresSaver. Coverage: TASK-040 integration, Supervisor,
Agent identity continuity, Tool permission, Task execution/resume, Approval decision,
Execution Ledger and Recovery. Extra probes rejected Task.result/checkpoint mismatch
and pending execution as success, and confirmed projection never invokes Runtime
run/resume. These are Reviewer-executed results, not tests rerun in this document-only
State Synchronization; Developer evidence remains separately recorded in TASK-040.

The only TASK-040 Reviewer NOTE is the independent read Session constraint:
`read_delegation_result` requires a fresh, dedicated read-only Session supplied by
the trusted caller. It calls `session.rollback()` before checkpoint access; a Session
with uncommitted writes can lose caller changes, and a stale ORM Session can yield
non-fresh durable state. This is an internal trusted API contract, documented and
used correctly by tests, not an open TASK-040 defect. A helper-owned read Session or
misuse guard may be considered if the calling surface expands; neither is implemented
or changed in this synchronization.

## Current Multi-Agent Capability Status

Completed Multi-Agent capabilities: TASK-035 Multi-Agent Architecture Research
(research deliverable), TASK-036 Agent Abstraction Layer, TASK-037 Agent Communication
Model, TASK-038 Supervisor Orchestration, TASK-039 Tool Permission Enforcement,
and TASK-040 Multi-Agent HITL Integration. Research completion does not imply
acceptance of the separately Proposed ADR-011.

Not yet completed: TASK-041 final demo packaging, Planner, dynamic routing,
scheduling, message persistence, rejection re-plan, multi-human approval,
Agent-to-Agent approval, generic historical provenance migration tooling, and
arbitrary delegation recovery beyond the reviewed existing recovery scenarios.

Next task: **TASK-041 - Multi-Agent Demo Packaging**. Status: **Not Started**.

## State Synchronization — Documentation-only delivery

Planned Write Set / actual synchronization changes (six documents):
- docs/CURRENT_STATE.md: latest completed TASK-040, final security/lifecycle evidence.
- docs/ARCHITECTURE.md: existing HITL ownership, Worker continuity and projection boundary.
- docs/AI_HANDOFF.md: current capability snapshot, Session NOTE, TASK-041 Not Started.
- docs/ROADMAP.md: TASK-040 Completed / PASS WITH NOTES; TASK-041 remains Not Started.
- docs/DECISIONS.md: ADR-014 reviewed implementation semantics; Proposed retained.
- tasks/TASK-040.md: final review evidence separate from Developer results/history.

Resolved stale Awaiting Independent Review / Multi-Agent HITL not completed claims
against the supplied final Reviewer outcome and inspected source/tests. Application
TaskExecutionService wiring and retained-REQUEST projection are now complete;
HTTP wiring, message persistence and arbitrary delegation recovery are not implied.
No business code, tests or Reviewer NOTE implementation changed; no tests rerun.
No new technical debt introduced; the independent read Session contract remains a NOTE.

Workspace Boundary Verification: working directory and Git root verified as
E:\AIProjects\AgentFlow-AI. Repository-relative writes and resolved containment
checks used. No repository-external creation, modification, move or deletion.
Existing non-document tracked/untracked files verified unchanged by SHA-256.
No git add / commit / push. Awaiting Human Gate; no TASK-041 implementation begun.

Validation: git diff --check passed (exit 0); no tests rerun. Git status retains
7 tracked modified files and 3 untracked files, with no staged changes:
- Tracked: backend/app/agents/supervisor.py, backend/app/tasks/service.py,
  docs/AI_HANDOFF.md, docs/ARCHITECTURE.md, docs/CURRENT_STATE.md,
  docs/DECISIONS.md, docs/ROADMAP.md.
- Untracked: backend/app/tasks/delegation.py, backend/tests/test_multi_agent_hitl.py,
  tasks/TASK-040.md.
The four backend source/test files are pre-existing changes preserved unchanged;
only the six planned documents were written during State Synchronization.

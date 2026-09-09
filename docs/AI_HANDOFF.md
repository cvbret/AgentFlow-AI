# AI Handoff Context

## Purpose / 文件用途

This file provides a compact project handoff context for a new AI assistant or coding agent.

该文件用于让新的 AI 快速恢复项目当前状态，而不需要重新阅读完整聊天记录。它是 `Current Project Snapshot`，不是历史日志。

Chat history is not the source of truth. Repository documentation and Git history are the source of truth.

## Current Project / 当前项目

* **Project:** `AgentFlow-AI`
* **Positioning:** Enterprise-oriented AI Agent backend
* **Current Phase:** `Phase 1 - Core Agent Runtime`

## Latest Completed Task / 最近完成任务

* **Task:** `TASK-028 - Approved Tool Resume Integration`
* **Review Result:** `PASS`
* **Summary:** durable protected Tool HITL pause/resume integrated; real Agent Graph uses PostgreSQL checkpoint; checkpoint-first pause; atomic APPROVED + RUNNING continuation claim; fresh Runtime resume; persisted Approval authorization; approved protected Tool continuation; cursor-based no-replay of preceding Tools; no crash-safe exactly-once yet; 318 passed, 0 skipped, 0 warnings
* **Git commit:** `Pending commit`

TASK-028 已通过最终 Independent Review，最终 Review Result 为 `PASS`，当前尚未提交。

## Compatibility Note / 兼容性说明

ConfigurationError currently lives in `app.core.config`.
The legacy import path remains usable, but ConfigurationError is no longer a subclass of LLMClientError.
No current repository caller depends on that inheritance relationship.
Review compatibility if the public error hierarchy is formalized later.

## Non-blocking Notes / 非阻塞说明

* Note: 既有 `TD-001 / StarletteDeprecationWarning`。
* Note: side-effectful Tool 当前仍可暴露给 LLM，但会在 execution boundary 被 fail closed；该行为属于 TASK-019 当前 Scope，不是新的 Technical Debt。
* Note: `Approval.arguments` 在构造时使用 Level A defensive snapshot；当前未承诺返回对象完全不可变，不阻塞 TASK-020，也不新增 Technical Debt。
* Note: Alembic 当前通过统一 Settings 读取 LLM 配置；本次使用 session-local harmless placeholders 完成 migration verification，已记录为 TD-005。
* Note: `TD-001 / StarletteDeprecationWarning` 仍是既有 Technical Debt；TASK-026 final suite 报告 0 warnings。
* Note: AgentFlow business persistence 与 LangGraph checkpoint persistence 是独立 durable boundaries，当前没有跨两者 transaction atomicity、reconciliation 或 exactly-once 保证。
* Note: TASK-028 Reviewer 独立验证 318 passed、0 skipped、0 warnings；无 crash-safe exactly-once 保证。

## Current Next Task / 当前下一任务

* **Task:** `TASK-029 - Protected Tool Idempotency / Execution Ledger`
* **Status:** `Not Started`

当前已建立 durable protected Tool pause/resume；下一阶段进入 Protected Tool Idempotency / Execution Ledger。当前不开始执行 TASK-029。

## Important Architecture Constraints / 当前重要架构约束

* V1 暂不引入 LangChain。
* LangGraph has been adopted incrementally from TASK-026。
* LangGraph 当前作为 orchestration layer，负责 workflow state、checkpoint、interrupt、resume 和 routing foundation。
* TASK-027 后 AgentRuntime 仍为 application-facing façade，实际 Agent loop orchestration 由 LangGraph StateGraph 承担。
* 不提前引入 MCP。
* 不提前实现 Multi-Agent。
* Repository 是 Source of Truth。
* Architecture changes 必须进入 `docs/DECISIONS.md`。
* Durable task state 当前使用 PostgreSQL，作为持久化 Agent Task 的 Source of Truth。
* Redis 不作为 durable Agent Task 的唯一 Source of Truth。
* Agent execution 后期必须有 bounded loop / failure handling。
* 不为了“企业级”而提前制造无需求的 abstraction。
* AI coding agents must not write outside `E:\AIProjects\AgentFlow-AI`。
* TASK-014：explicit bounded LLM request timeout。
* TASK-015：failure classification / retryable signal。
* TASK-016：bounded retry / `max_attempts`。
* TASK-017：exponential backoff + bounded jitter。
* V1 LLM Reliability Foundation 已基本形成。
* Retry-After、circuit breaker、global retry budget、provider-specific retry policy 和 adaptive retry 尚未建立。
* TASK-018：Tool execution safety metadata foundation 已建立；unknown/unannotated Tool 默认按可能有副作用处理，Calculator 显式 `side_effect_free=True`。
* TASK-019：ToolExecutionPolicy 已进入 Tool execution boundary；仅 `side_effect_free=True` 允许 automatic execution，否则在 `Tool.execute()` 前 fail closed。
* Tool safety decision 来自 Registry 返回的真实 Tool metadata，不信任外部 ToolCall 或 caller-supplied safety flag。
* Protected Execution Boundary 已建立；approval decision、durable HITL pause、approved Tool continuation 和 fresh Runtime resume 已建立，但 crash-safe exactly-once、idempotency 和 Execution Ledger 尚未实现。
* TASK-020：Approval 是独立于 TaskStatus 的 Domain Entity；一个 Task 概念上可关联多个 Approval。
* 新 Approval 只能从 `PENDING` 创建；历史 Approval 通过 `restore(...)` 进行受控恢复。
* TASK-021：Approval persistence 已建立；`Approval ORM` 不等于 `Approval Domain Entity`，历史实体通过 `Approval.restore(...)` 重新水合。
* Approval API、Agent pause/resume、ToolExecutionPolicy 自动创建 Approval 以及 approved Tool execution 已分阶段建立；crash-safe exactly-once、idempotency、Execution Ledger 和 reconciliation 尚未实现。
* TASK-022：`ProtectedToolExecutionService` 协调 safety policy、`ApprovalRepository` 与 `ToolExecutor`；protected ToolCall 创建持久化 `PENDING` Approval 后抛出 `ApprovalRequired`。
* Safe Tool 保持 exactly-once automatic execution；side-effectful Tool 与 persistence failure 均不会调用 `Tool.execute()`。
* TASK-023：`AgentRuntime → ProtectedToolExecutionService → ApprovalRequired → TaskExecutionService → HITLPausePersistence`，以单次短事务原子持久化 Approval(PENDING) 与 Task(WAITING_APPROVAL)。
* 失败处理使用 conditional RUNNING → FAILED update；0 rows 不表示 waiting success confirmed，commit acknowledgement uncertainty 尚未完整 reconciliation。
* TASK-024：`POST /api/approvals/{id}/approve|reject → ApprovalDecisionService → Approval Domain → conditional Approval persistence`；并发决策保证单一成功者，冲突返回 409。
* Decision API 不调用 AgentRuntime、LLM、ToolExecutor 或 ProtectedToolExecutionService；`APPROVED` / `REJECTED` 后 Task 仍为 `WAITING_APPROVAL`。
* TASK-025：reject 通过 `ApprovalDecisionService → Approval.reject() + Task.mark_rejected() → ApprovalRejectionPersistence`，在一个短事务中原子写入 `REJECTED Approval + REJECTED Task`；approve 仍保持 `APPROVED + WAITING_APPROVAL`。
* `REJECTED` 不等于 `FAILED`；decision paths 不执行 Tool。未来新增其它 WAITING_APPROVAL 出站路径时，必须重新评估跨实体并发边界。
* TASK-026：LangGraph durable workflow foundation 已建立；TASK-027 将 Agent loop orchestration 迁移至 LangGraph StateGraph；TASK-028 将 real Agent checkpoint-first protected Tool pause/resume 接入。LangGraph 仅负责 orchestration/checkpoint，AgentFlow 保留 LLMClient、LLM reliability、Tool/Registry/Executor/Policy、Domain、Services、Repositories、business persistence 和 FastAPI。
* Business persistence 由 SQLAlchemy / Repository / Alembic 管理；workflow persistence 由 PostgreSQL-backed PostgresSaver 管理，LangGraph checkpoint tables 不由 AgentFlow Alembic 管理。
* AgentFlow business state、LangGraph workflow state 和 external side effects 仍是三个独立关注面；TASK-028 连接了正常 continuation，但没有跨三者 transaction atomicity，也没有 crash-safe exactly-once、reconciliation 或 duplicate prevention 保证。
* TASK-028 已建立 checkpoint-first pause、`WAITING_APPROVAL → RUNNING` continuation claim、Approval-driven resume、approved Tool continuation 和 cursor-based no-replay；Execution Ledger、idempotency、orphan cleanup、stale RUNNING recovery 与 reconciliation 仍属 TASK-029 及后续能力。

Resume Architecture Readiness = Ready；real Agent durable resume 与 approved Tool continuation 已建立，但 crash-safe exactly-once 与 Execution Ledger 仍属于后续任务。

AI coding workflow currently uses Workspace Boundary Guard v1，包括：

* root verification
* repository-relative path preferred
* repository-internal absolute path only when tool requires it
* containment verification required
* repository-external write = violation
* post-write audit

Hard filesystem sandbox is not yet implemented.

PI-001 process incident status: `Mitigated`.

AgentFlow-AI repository root 同时也是 AI Coding Agent 的文件系统施工边界。

## Development Workflow / 当前 AI 辅助开发流程

```text
Task Definition
  → Developer Agent
  → Automated Tests
  → Independent Reviewer
  → Fix if Required
  → Project State Synchronization
  → Human Gate
  → Git Commit
```

* **Developer Agent：**负责实现当前 Task。
* **Independent Reviewer：**独立检查 Requirement、Architecture、Tests、Scope 和风险。
* **Human Gate：**由用户决定是否接受、是否提交。

## Context Loading Strategy / AI 上下文加载策略

### Always Read / 始终阅读

新的 Architect / Mentor AI 优先阅读：

1. `docs/PROJECT.md`
2. `docs/CURRENT_STATE.md`
3. `docs/AI_HANDOFF.md`
4. `AGENTS.md`
5. 当前 Task

### Read When Relevant / 按需阅读

根据任务读取：

* `docs/ARCHITECTURE.md`
* `docs/ROADMAP.md`
* `docs/DECISIONS.md`
* `docs/TECH_DEBT.md`
* relevant source code
* relevant tests
* recent Git diff / Git history

目标不是把整个 repository 都塞进 context，而是提高 context 的信噪比。

## Learning Context / 当前教学上下文

用户已经理解：

* Agent 接收 Task
* 基础 Planning / Reasoning
* Tool Calling
* Tool Result
* State Update
* LLM 根据结果决定下一步
* Agent execution loop 的基本概念

因此不需要重新从“什么是 Agent”开始教学。当前应重点学习：

* enterprise Agent architecture
* LLM abstraction
* Tool architecture
* state management
* workflow orchestration
* reliability
* testing
* observability
* long-term AI-assisted development workflow

本文件不记录与项目无关的个人信息。

## Known Technical Debt / 当前已知技术债

* `TD-001` — TestClient dependency deprecation warning
* `TD-002` — Backend working-directory dependency
* `TD-003` — LLM HTTP timeout is not explicitly configured (Closed by TASK-014)
* `TD-004` — Calculator accepts non-finite and boolean numeric inputs
* `TD-005` — Alembic configuration coupled to LLM application settings

这里只做摘要；详细信息仍以 `docs/TECH_DEBT.md` 为 Source of Truth。

## Handoff Rules / 交接规则

`AI_HANDOFF.md` 不应该无限增长。它是当前快照，不是 append-only history。

每次 Task 完成后，按需更新：

* Latest Completed Task
* Current Next Task
* Important Architecture Constraints
* Known Technical Debt 摘要
* Learning Context

历史信息应由 Git history、`tasks/`、`docs/DECISIONS.md` 和 `docs/TECH_DEBT.md` 保存。

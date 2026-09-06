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

* **Task:** `TASK-016 - Bounded LLM Retry Policy`
* **Review Result:** `PASS WITH NOTES`
* **Summary:** `LLM_MAX_ATTEMPTS` default `3`; bounded provider retry; `retryable=True` controls retry; non-retryable fail-fast; attempt exhaustion preserves final failure; Agent/Task lifecycle unaffected; 147 passed, 24 skipped, 1 warning
* **Git commit:** `Pending commit`

TASK-016 已通过 Independent Review，最终 Review Result 为 `PASS WITH NOTES`，当前尚未提交。

## Compatibility Note / 兼容性说明

ConfigurationError currently lives in `app.core.config`.
The legacy import path remains usable, but ConfigurationError is no longer a subclass of LLMClientError.
No current repository caller depends on that inheritance relationship.
Review compatibility if the public error hierarchy is formalized later.

## Non-blocking Notes / 非阻塞说明

* Note: Pydantic 对部分 integer-compatible 输入存在 coercion，例如 `3.0 → 3`、`True → 1`；当前作为 Review NOTE 保留，未升级为 Technical Debt。
* Note: 当前环境无 `DATABASE_URL`，因此 24 个 PostgreSQL integration tests 未执行。
* Note: 既有 `StarletteDeprecationWarning` 仍存在，对应 `TD-001`。

## Current Next Task / 当前下一任务

* **Task:** `Reliability - retry timing / backoff policy`
* **Status:** `Not Started`

当前尚未定义为具体 Task，暂不开始执行。

## Important Architecture Constraints / 当前重要架构约束

* V1 暂不引入 LangChain。
* V1 暂不引入 LangGraph。
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
* Backoff、jitter、Retry-After 和 retry timing policy 尚未建立。

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

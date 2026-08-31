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

* **Task:** `TASK-001 - Minimal FastAPI Application`
* **Review Result:** `PASS WITH NOTES`
* **Implementation:** FastAPI application established; `GET /api/health`; automated API tests; Uvicorn startup independently verified
* **Git commit:** `6b5c6c6 feat: implement TASK-001 minimal FastAPI application`

以上 commit hash 来自当前 repository 的 `git log --oneline`，不是推测值。

## Current Next Task / 当前下一任务

* **Task:** `TASK-002 - First LLM Client Abstraction`
* **Status:** `Not Started`

TASK-002 只是下一项任务，尚未开始。

## Important Architecture Constraints / 当前重要架构约束

* V1 暂不引入 LangChain。
* V1 暂不引入 LangGraph。
* 不提前引入 MCP。
* 不提前实现 Multi-Agent。
* Repository 是 Source of Truth。
* Architecture changes 必须进入 `docs/DECISIONS.md`。
* Durable task state 未来优先使用 PostgreSQL。
* Redis 不作为 durable Agent Task 的唯一 Source of Truth。
* Agent execution 后期必须有 bounded loop / failure handling。
* 不为了“企业级”而提前制造无需求的 abstraction。

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

# AgentFlow-AI Architecture

## Current Logical Architecture / 当前逻辑架构

This document describes the current target architecture for Phase 1. It records boundaries that are useful now; it does not claim that every component has already been implemented.

本文记录 Phase 1 当前需要遵守的逻辑边界，不把未来所有设想当成现有实现。

```text
Client
  ↓
FastAPI
  ↓
Task Service
  ↓
Agent Runtime
  ├── LLM Client
  └── Tool Registry
        ↓
       Tool
```

## API Layer / API 层

The API layer handles HTTP request handling, request validation, and response formatting.

中文释义：这一层负责把外部 HTTP 请求转换为应用层可以理解的输入，并把结果转换成稳定的 API 响应。它不得承担 Agent 执行循环、工具实现或 LLM 推理逻辑，否则接口协议和运行时行为会耦合在一起，难以测试和演进。

当前已建立单 Task 查询接口：`GET /api/tasks/{task_id}`。查询边界为：

`API → TaskRepository → Domain Task → Response DTO`

查询接口使用独立的 `TaskQueryResponse` DTO，不直接暴露 ORM Model。

列表查询接口的边界为：

`GET /api/tasks → TaskRepository.list(limit, offset) → Domain Task list → TaskListResponse`

列表分页使用确定性排序：`created_at DESC, id DESC`。

`POST /api/agent/run` 成功响应返回 `task_id + answer`，其中 `task_id` 来自 `TaskExecutionService` 返回的真实 Domain `Task.id`。当前资源闭环为：

`POST /api/agent/run → task_id + answer → GET /api/tasks/{task_id}`

## Task / Application Layer / Task 应用层

The Task Service coordinates the application-level flow for one task. It should connect the API contract to the Agent Runtime without mixing HTTP concerns, database concerns, and raw LLM calls into one function.

中文释义：Task Service 负责协调“一次任务”的应用逻辑，例如接收任务、调用 Runtime、整理结果和处理应用层状态。它不是所有逻辑的收容所；HTTP、数据库和 LLM 的具体细节应由各自边界负责。

## Agent Runtime / Agent Runtime 层

The Agent Runtime is responsible for:

* submitting context to the LLM
* receiving tool calls
* resolving and executing a Tool
* returning the tool result to the LLM
* controlling the Agent Loop
* deciding when execution has ended

中文释义：这是 Agent 的核心执行边界。Runtime 协调模型和工具，但不应把每个具体业务工具硬编码进去。它未来还必须拥有最大步骤数、超时、重试和失败分类等可靠性控制。

## Tool Layer / Tool 层

At minimum, a Tool has:

* `name`
* `description`
* `input schema`
* `implementation`

中文释义：工具必须有可识别的名称、给模型和开发者看的描述、结构化输入定义以及真实实现。未来再根据明确需求增加 timeout、retry、permissions 和 side-effect classification；当前不提前设计完整工具平台。

## State Layer / 状态层

**Current status: durable task state persistence implemented.**

中文释义：当前仓库已通过 `TaskRepository` 和 PostgreSQL 实现 durable task state；执行历史仍未实现。

The Task Service persists the task lifecycle through:

`PENDING → RUNNING → SUCCEEDED / FAILED`

`TaskExecutionService` coordinates this lifecycle with the Agent Runtime. Each API request uses a request-scoped SQLAlchemy Session.

The expected future responsibility is:

* **PostgreSQL:** durable task state and the durable source of truth; execution history remains future scope.
* **Redis:** cache, temporary state, and locks.

Redis must not be the only source of truth for a durable Agent Task.

中文释义：持久任务需要一个可恢复、可审计的最终事实来源。Redis 适合短期数据和协调用途，但不应单独承担任务最终状态，否则重启、过期或数据丢失后无法可靠恢复。

## Dependency Direction / 依赖方向

Dependencies should point downward:

```text
API
 ↓
Application / Task Service
 ↓
Agent Runtime
 ↓
LLM / Tools / Infrastructure
```

上层可以调用下层定义的接口，下层不应反向依赖 HTTP 路由或具体 API 实现。各层之间应避免循环依赖，并通过清晰的边界传递数据。

## Architecture Rule / 架构规则

Any material architecture change must be recorded in `docs/DECISIONS.md` as a new ADR. Existing ADRs are historical records and must not be overwritten to hide the earlier decision.

中文释义：重大架构选择必须留下可追溯记录。后续即使改变方向，也应追加新的 ADR，说明背景、决定和后果，而不是修改旧记录让历史消失。

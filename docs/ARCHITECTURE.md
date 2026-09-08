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

列表接口支持可选的单一 status filter。查询顺序为：

`GET /api/tasks → optional status filter → TaskRepository.list(...) → SQL WHERE → deterministic ordering → limit / offset → TaskListResponse`

允许的 status 值为 `pending`、`running`、`succeeded`、`failed` 和 `waiting_approval`。

`POST /api/agent/run` 成功响应返回 `task_id + answer`，其中 `task_id` 来自 `TaskExecutionService` 返回的真实 Domain `Task.id`。当前资源闭环为：

`POST /api/agent/run → task_id + answer → GET /api/tasks/{task_id}`

## Task / Application Layer / Task 应用层

The Task Service coordinates the application-level flow for one task. It should connect the API contract to the Agent Runtime without mixing HTTP concerns, database concerns, and raw LLM calls into one function.

中文释义：Task Service 负责协调“一次任务”的应用逻辑，例如接收任务、调用 Runtime、整理结果和处理应用层状态。它不是所有逻辑的收容所；HTTP、数据库和 LLM 的具体细节应由各自边界负责。

## Approval Domain / Approval 领域

`Approval` 是独立于 `TaskStatus` 的 Domain Entity，用于表示某一次 protected ToolCall 的人工决策；`Task` 表示整个 Agent execution。一个 Task 概念上可关联多个 Approval，但本阶段不提前定义 ORM 或 database relationship。

新 Approval 只能以 `PENDING` 创建；历史实体通过独立的 `Approval.restore(...)` 路径受控恢复。`APPROVED` 和 `REJECTED` 是 terminal states。

Approval persistence boundary 为：

`Approval Domain ↔ ApprovalRepository ↔ ApprovalRecord ORM ↔ PostgreSQL`

`ApprovalRecord` 不等于 `Approval` Domain Entity。读取持久化记录时必须通过 `Approval.restore(...)` 重新水合，以继续执行 Domain invariants。本阶段仅建立 `create`、`get_by_id` 和 `save`，不提前扩展为通用 Repository framework。

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

中文释义：工具必须有可识别的名称、给模型和开发者看的描述、结构化输入定义以及真实实现。

Tool 还可携带内部 execution safety metadata，例如 `side_effect_free`。Tool 的 execution safety boundary 为：

`ToolExecutor → Registry.get() → tool.metadata() → ToolExecutionPolicy → Tool.execute()`

仅当 `side_effect_free=True` 时允许 automatic execution；未知或未标注的 Tool 默认按可能具有副作用处理，并在 `Tool.execute()` 前 fail closed。安全决策来自 Registry 返回的真实 Tool，不信任外部 ToolCall 或 caller-supplied safety flag。该 metadata 不属于 provider-facing tool schema，side-effectful Tool 仍可注册并暴露给 provider，但执行时会被拒绝。AgentRuntime 不直接承担该策略判断。

Protected ToolCall request 由 `ProtectedToolExecutionService` 负责：接收真实 `task_id` 与 `ToolCall`，复用 `ToolExecutionPolicy`。safe ToolCall 委托 `ToolExecutor` 执行；side-effectful Tool 仅构造未持久化的 `PENDING` Approval，通过携带该实体及 identity 字段的 `ApprovalRequired` 立即停止执行。

TASK-023 路径为 `TaskExecutionService → AgentRuntime.run(task_id) → ProtectedToolExecutionService`。Runtime 无数据库依赖。TaskExecutionService 捕获 signal，在通过 `Task.restore` 构造的候选 Task 上执行 WAITING_APPROVAL transition，再调用 `HITLPausePersistence`：同一请求 Session 中 stage Approval、flush、stage Task WAITING、flush、单次 commit。事务只覆盖这一短持久化窗口，不跨越 Agent/LLM 调用。成功后才返回 waiting Task。

任一写入或 commit 失败时回滚整个 pause transaction；原 Domain Task 仍为 RUNNING，随后合法进入 FAILED 并单独 best-effort 保存。失败持久化使用单条带 `id` 与 `status=RUNNING` 条件的 UPDATE，仅 durable state 仍是 RUNNING 才更新为 FAILED。若 commit 已成功但确认丢失，更新零行，保留 WAITING_APPROVAL；零行不代表已确认暂停成功。FAILED 保存本身也可能失败，原始错误继续传播；不返回伪造的 waiting 成功。Standalone Repository create/save 继续拥有 commit，新增 staging 方法不 commit。详见 ADR-003 / TD-006。

`POST /api/agent/run` 返回 `task_id + status + answer`，其中 status 为 `succeeded` 或 `waiting_approval`，暂停时 answer 为 null。Task 查询与过滤支持小写 `waiting_approval`。TASK-024 已实现 Approval decision API（见下节）；当前未实现 resume、approved Tool execution 或 idempotency。`ProtectedToolExecutionService` 与 `ToolExecutor` 当前存在无状态且语义一致的 double policy evaluation，暂不为此扩大架构范围。

## State Layer / 状态层

**Current status: durable task state persistence implemented.**

中文释义：当前仓库已通过 `TaskRepository` 和 PostgreSQL 实现 durable task state；执行历史仍未实现。

The Task Service persists the task lifecycle through:

`PENDING → RUNNING → SUCCEEDED / FAILED / WAITING_APPROVAL`

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


## Approval Decision Application Boundary (TASK-024)

`POST /api/approvals/{approval_id}/approve|reject → ApprovalDecisionService → Approval.approve()/reject() → ApprovalRepository.save_decision_if_pending() → PostgreSQL`。

Service 与两个 Repository 使用请求级 Session。Service 读取关联 Task，仅允许 WAITING_APPROVAL 上的 PENDING Approval。数据库通过单条条件 UPDATE（PENDING、Task identity、关联 Task WAITING 条件）保护竞争，只写 status/decided_at；提交成功才返回 terminal DTO。重复或竞争失败返回 409，不存在 Approval 返回 404，无效 Task context 返回 409，数据库错误回滚并传播。

Decision 不调用 Runtime/Tool。Approve 后 Task 仍为 WAITING_APPROVAL；TASK-025 reject 则在一个短事务中同时将 Approval 与 Task 变为 REJECTED（见 ADR-004）。既有 standalone save 兼容保留，decision 路径必须使用条件写入。该能力不包含 resume、reconciliation 或完整 idempotency；commit acknowledgement 丢失仍可返回错误，不自动重试或推断成功。


## Human Rejection Lifecycle (TASK-025)

`ApprovalDecisionService → Approval.reject() + Task.mark_rejected() → ApprovalRejectionPersistence → stage_decision_if_pending + stage_rejected_if_waiting → one commit`。

Task 仅允许 WAITING_APPROVAL → REJECTED，REJECTED 为 terminal 且无 result/error；人工拒绝不等同 FAILED。两次数据库条件写入分别要求 Approval PENDING 和 Task WAITING_APPROVAL，冲突或错误回滚整个 rejection transaction。提交结果不确定时只传播错误，不执行 fallback write。该短事务包含 context reads 和持久化，不跨 LLM/Runtime/Tool。

Task 查询及 `GET /api/tasks?status=rejected` 支持新状态。Approval API DTO 不变。Approve 继续保持 WAITING_APPROVAL，不恢复执行。

## Durable Workflow Foundation (TASK-026 / ADR-005)

The isolated app.workflows package provides START -> durable_pause (interrupt) -> END. It does not replace AgentRuntime or APIs. State contains only task_id and optional resume_result strings, with no runtime objects or business lifecycle snapshots.

AgentFlow Task.id -> task_id_to_thread_id -> LangGraph configurable.thread_id. LangGraph internal task IDs are distinct. The interrupt node has no pre-interrupt side effects and is replay-safe.

open_checkpointer owns a synchronous official PostgresSaver connection. Run python -m app.workflows.setup explicitly from backend with DATABASE_URL for infrastructure initialization. Normal open/startup never calls setup. Checkpoint schema belongs to LangGraph; business tables remain owned by SQLAlchemy/Alembic.

Restart tests close process A before process B creates a fresh graph/checkpointer and resumes the persisted thread with Command(resume), without initial input. Separate thread isolation and final state are verified.

LangGraph owns orchestration/checkpoint foundation. AgentFlow retains Domain, Services, Repositories, Tool safety, LLM reliability and FastAPI. Business/checkpoint consistency is recognized and deferred to a separately designed integration task.

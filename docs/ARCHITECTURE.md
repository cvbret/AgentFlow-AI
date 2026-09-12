# AgentFlow-AI Architecture

## Current Logical Architecture / 当前逻辑架构

This document describes the current implemented architecture and the enduring boundaries for Phase 1. It records remaining optional boundaries without claiming future capabilities are already implemented.

本文记录 Phase 1 当前已实现的逻辑架构与必须遵守的边界；仍将未来可选能力与现有实现区分开来。

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

真实 Provider validation 已确认以下运行链路：

`FastAPI → Task Service / PostgreSQL → AgentRuntime → LangGraph StateGraph → LLMClient → OpenAI-compatible Provider (DeepSeek) → Tool Calling → Protected Tool Execution / Tool Registry → Tool Result → LLM → final_answer → Task persistence → HTTP Response`

DeepSeek 仅是当前开发环境中完成验证的 Provider；`LLMClient` 与整体架构保持 OpenAI-compatible、provider-neutral，不构成 DeepSeek-specific framework。

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

中文释义：这是 Agent 的核心执行边界。Runtime 协调模型和工具，但不应把每个具体业务工具硬编码进去。当前已具备最大步骤数、超时、重试和失败分类等可靠性控制；真实 Provider HTTP E2E 也已在开发环境完成验证。

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

`POST /api/agent/run` 返回 `task_id + status + answer`，其中 status 为 `succeeded` 或 `waiting_approval`，暂停时 answer 为 null。Task 查询与过滤支持小写 `waiting_approval`。TASK-024 建立 Approval decision API；后续 TASK-028/029/030 已建立 approved Tool resume、Execution Ledger 与 operator-triggered recovery。`ProtectedToolExecutionService` 与 `ToolExecutor` 当前存在无状态且语义一致的 double policy evaluation，暂不为此扩大架构范围。

## State Layer / 状态层

**Current status: durable task state, protected resume, Execution Ledger, recovery and structured observability implemented.**

中文释义：当前仓库已通过 `TaskRepository`、Execution Ledger、Recovery Service 和 PostgreSQL 实现 durable task execution；持久化 audit log、metrics backend 与 distributed tracing backend 仍未实现。

The Task Service persists the task lifecycle through:

`PENDING → RUNNING → SUCCEEDED / FAILED / WAITING_APPROVAL`

`TaskExecutionService` coordinates this lifecycle with the Agent Runtime. Each API request uses a request-scoped SQLAlchemy Session.

Current responsibility and remaining boundary are:

* **PostgreSQL:** durable task state and the durable source of truth; persistent audit history remains future scope.
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

TASK-024/025 阶段 Decision 不调用 Runtime/Tool，approve 后 Task 保持 WAITING_APPROVAL（TASK-028 已升级，见下文）；TASK-025 reject 则在一个短事务中同时将 Approval 与 Task 变为 REJECTED（见 ADR-004）。既有 standalone save 兼容保留，decision 路径必须使用条件写入。该能力不包含 resume、reconciliation 或完整 idempotency；commit acknowledgement 丢失仍可返回错误，不自动重试或推断成功。


## Human Rejection Lifecycle (TASK-025)

`ApprovalDecisionService → Approval.reject() + Task.mark_rejected() → ApprovalRejectionPersistence → stage_decision_if_pending + stage_rejected_if_waiting → one commit`。

Task 仅允许 WAITING_APPROVAL → REJECTED，REJECTED 为 terminal 且无 result/error；人工拒绝不等同 FAILED。两次数据库条件写入分别要求 Approval PENDING 和 Task WAITING_APPROVAL，冲突或错误回滚整个 rejection transaction。提交结果不确定时只传播错误，不执行 fallback write。该短事务包含 context reads 和持久化，不跨 LLM/Runtime/Tool。

Task 查询及 `GET /api/tasks?status=rejected` 支持新状态。Approval API DTO 不变。TASK-028 将 approve 升级为原子 continuation claim，reject 行为不变。

## Durable Workflow Foundation (TASK-026 / ADR-005)

The isolated foundation graph provides START -> durable_pause (interrupt) -> END. Its input remains task_id with optional resume_result; it is separate from the Agent execution graph introduced in TASK-027. The shared AgentGraphState additionally permits Agent loop fields and a serialized pending request for correlation; runtime objects are excluded. Approval decisions remain authoritative only in business persistence.

AgentFlow Task.id -> task_id_to_thread_id -> LangGraph configurable.thread_id. LangGraph internal task IDs are distinct. The interrupt node has no pre-interrupt side effects and is replay-safe.

open_checkpointer owns a synchronous official PostgresSaver connection. Run python -m app.workflows.setup explicitly from backend with DATABASE_URL for infrastructure initialization. Normal open/startup never calls setup. Checkpoint schema belongs to LangGraph; business tables remain owned by SQLAlchemy/Alembic.

Restart tests close process A before process B creates a fresh graph/checkpointer and resumes the persisted thread with Command(resume), without initial input. Separate thread isolation and final state are verified.

LangGraph owns orchestration/checkpoint foundation. AgentFlow retains Domain, Services, Repositories, Tool safety, LLM reliability and FastAPI. TASK-028 establishes checkpoint-first ordering; cross-store atomicity and reconciliation remain deferred.


## Agent Runtime Orchestration (TASK-027, extended by TASK-028)

AgentRuntime remains the application-facing facade: run(initial_messages, *, task_id)
and resume(*, task_id, approval_id) return AgentResult(content), or expose
ApprovalRequired after a durable interrupt. API routes do not invoke Graph APIs.
The application runtime factory injects a fresh PostgresSaver context per invocation
and an Approval loader using a separate short business Session. Infrastructure must
run `python -m app.workflows.setup` before serving Agent requests; startup does not
silently create checkpoint tables. Runtime.close still owns LLMClient.close.

Standalone runtime construction without a saver retains the earlier non-durable
ApprovalRequired behavior for compatibility and unit use; it cannot resume. The
production dependency factory always wires PostgreSQL checkpoints. No in-memory
saver is used for the acceptance path.

```text
START -> llm -> route -> END / tool
                              tool -> llm (all calls complete)
                              tool -> approval_pause -> interrupt
                                          resume -> tool (saved cursor)
```

The tool node executes ordered calls through ProtectedToolExecutionService.
On ApprovalRequired it RETURNS completed messages, the current cursor and a JSON
snapshot of the same pending Approval. That node completes before approval_pause
runs. The pause node has no pre-interrupt business side effects and validates only
correlation on replay. It does not decide an Approval or execute a Tool.

AgentGraphState uses JSON-compatible message/ToolCall snapshots, task_id,
step_count, max_steps, final_answer, tool_calls, tool_cursor, pending_approval and
resume_approval_id. Optional resume_result remains foundation-only. ChatMessage
and ToolCall are reconstructed at the LLM/Tool boundary; no LangChain messages
are introduced. Pending Approval data preserves identity/context for first business
persistence and is NEVER decision authority. No Session, Tool or service is state.

For safe A / protected B / safe C, the checkpoint records A's result and the cursor
at B. Successful resume executes B then C; A is not replayed. A later protected
call returns a new pending Approval and enters WAITING_APPROVAL again.

max_steps still bounds LLM calls, including the last tool-producing round. Both
step_count and the original budget survive resume, even if a fresh runtime has a
different default. Last-round tools execute before exhaustion; a final answer on
the boundary succeeds. recursion_limit = 2 * persisted max_steps + 4 is an extra
framework guard per invocation. LLMClient retains all provider/reliability logic;
Tool.execute retains input validation and ToolResult/error handling.

## Approved Continuation (TASK-028 / ADR-006)

1. Graph invoke completes its durable checkpoint/interrupt before Runtime exposes
   ApprovalRequired with the original Approval ID and ToolCall context.
2. Existing HITLPausePersistence atomically inserts PENDING Approval and writes
   WAITING_APPROVAL Task. A failed business write cannot execute the protected
   Tool; an orphan checkpoint may remain. Checkpoint failure does not expose a
   business pause.
3. ApprovalDecisionService calls Approval.approve and Task.resume_approved, then
   ApprovalContinuationPersistence conditionally writes PENDING -> APPROVED and
   WAITING_APPROVAL -> RUNNING in one short PostgreSQL transaction. Both decision
   paths lock/update Approval before Task. A losing conditional update rolls back
   both writes. Only the winner dispatches continuation, after commit.
4. TaskResumeService ends its Task read transaction before invoking Runtime.resume.
   It reuses TaskExecutionService's running-task completion/failure/pause handling:
   SUCCEEDED, conditional FAILED, or a new WAITING_APPROVAL. No transaction spans
   Graph execution, LLM or Tool side effects.
5. Runtime validates durable thread/Approval correlation and persisted approval
   before Command(resume). ApprovedToolExecutionService rereads business Approval
   and requires APPROVED plus exact approval ID, task ID, tool_call_id, tool name
   and JSON arguments before execution-ledger inspection (TASK-029), Registry resolution and Tool.execute. Payloads are
   correlation only; no approved boolean, force flag or generic policy bypass.

Approval routes and successful response DTOs are unchanged. Approve dispatches
synchronous continuation via the application service; query Task for its resulting
state. Continuation failures propagate through existing error handling after the
committed decision, with best-effort FAILED persistence. Retrying the decision
returns conflict and does not dispatch another resume. Reject never resumes.

There is no crash-safe exactly-once guarantee. TASK-029 below adds cached-result
replay when the execution ledger has durably recorded success, and fail-closed
handling when it has not. External outcomes can still be ambiguous. A committed RUNNING claim followed by dispatch/process failure
can leave stale RUNNING state. Orphan checkpoints, commit acknowledgement
uncertainty and cross-store reconciliation are not repaired in this task.
TASK-029 owns ledger/idempotency/duplicate prevention; later recovery and
reconciliation work (TASK-030 scope to be defined) remains separate. No automatic
recovery, queue, worker, parallel approvals or distributed execution is added.


## Protected Tool Execution Ledger (TASK-029 / ADR-007)

ApprovedToolExecutionService always verifies persisted APPROVED authorization
before consulting the Execution Ledger, including before returning a cached result.
The ledger cannot grant human authorization. Graph state and checkpoint tables
are unchanged; existing task_id and ToolCall.id identify the business execution.

ToolExecution is a separate execution Domain entity. tool_executions is a business
table managed by SQLAlchemy and Alembic migration 0003_create_tool_executions.
Execution UUID is independent of Approval UUID; UNIQUE(task_id, tool_call_id)
defines business uniqueness. idempotency_key is the stable string form of the
execution UUID, with a database unique constraint. Task and Approval foreign keys
are restrictive, matching repository conventions; no cascade deletion or ledger
cleanup policy is introduced.

ExecutionRepository owns a short Session for each read/claim/completion operation.
INSERT ... ON CONFLICT DO NOTHING uses the database business-key constraint;
a preceding inspection is an optimization, not the concurrency guard. A losing
claim loads the winner's identity/key/status. Claim commit must succeed before
Tool.execute; no business transaction spans external execution. Terminal writes
conditionally require the same UUID still in EXECUTING, and commit separately.

| Status | Meaning | Automatic repeated request |
| --- | --- | --- |
| EXECUTING | Durable claim; external effect may already have occurred | Fail closed |
| SUCCEEDED | Successful Tool result durably stored | Return stored ToolExecutionResult; no Tool call |
| FAILED | Explicitly known failure without external effect | Fail closed; no retry |
| UNKNOWN | External outcome is uncertain | Raise ToolExecutionOutcomeUnknown; no retry |

Domain enforces state/result/error/timestamp invariants and terminal transitions.
Stored errors are classification codes, not arbitrary provider exception messages.
Identity comparison includes task_id, tool_call_id, approval_id, tool name and
canonical JSON arguments. Sorting keys makes object insertion order irrelevant;
JSON types remain distinct and non-finite numeric values are rejected. The same
comparison is used by Approval authorization. A context mismatch never returns
an old result or executes a Tool.

Tool input validation is reused and performed before claiming; invalid input and
missing Tool resolution cannot produce an effect or create a ledger row. During
execution, only ToolExecutionFailedWithoutEffect explicitly establishes FAILED.
A generic ToolExecutionError does not prove the external outcome: it is recorded
as UNKNOWN, as is an explicit ToolExecutionOutcomeUnknown signal. A process exit
or a persistence failure can leave EXECUTING; automatic replay is still blocked.
Successful-result persistence errors do not trigger Tool retry or overwrite the
execution as FAILED. If commit succeeded but its acknowledgement was lost, a
fresh inspection finds SUCCEEDED and reuses the result.

ToolMetadata.idempotency_mode is NONE by default; EXTERNAL_KEY and INHERENT are
explicit capability descriptions independent of side_effect_free. Capabilities
do not grant automatic recovery rights in TASK-029. Existing Tool.execute(data)
and Calculator remain compatible. For EXTERNAL_KEY only, the approved boundary
passes ToolExecutionContext(idempotency_key=stored_key) to execute; Tool dispatches
to an explicit _execute_with_context hook. Missing context or an unimplemented
hook fails before external execution. Tools never receive an ExecutionRepository.
A fake endpoint proves equal keys share one external operation and different
executions receive distinct keys, without network dependencies.

Closed replay window: Tool effect succeeds -> ledger SUCCEEDED -> graph progress
not recorded -> controlled workflow replay returns the cached result and continues
LLM execution. A fresh graph/saver test proves effect count remains 1 before/after.
This does not introduce a failed-node recovery API, automatic scanner or worker.

Remaining window: Tool effect succeeds -> process crash before ledger success ->
EXECUTING remains. Its external outcome cannot be inferred from the ledger.
TASK-030 below adds operator-triggered, capability-gated recovery; ordinary
execution still rejects UNKNOWN and stale EXECUTING.
No universal crash-safe exactly-once guarantee. No retries, leases, heartbeats,
queue, worker, outbox, saga, two-phase commit or orphan checkpoint cleanup is added.

Migration verification must respect schema ownership. A raw `alembic check` against
a database also containing LangGraph tables sees those unowned tables as removal
differences; do not generate or apply their deletion. TASK-029 verifies the business
migration/ORM in an isolated business-only PostgreSQL database and runs acceptance
and full regression against the combined PostgreSQL setup.


## Operator Recovery (TASK-030 / ADR-008)

`POST /api/tasks/{task_id}/recover -> TaskRecoveryService` exposes a small response:
`task_id` and `outcome` (recovered, no_action, still_in_progress, recovery_required,
or orphan_checkpoint). No Graph JSON, ledger record, force flag or retry parameter
is exposed. Task Query/list filtering includes recovery_required. No background
scheduler, scanner, polling, worker or automatic deletion is installed.

RECOVERY_REQUIRED is an operational state: durable execution facts cannot yet be
safely reconciled. It is distinct from a known FAILED result or human REJECTED
outcome, and carries neither result nor error. RUNNING/WAITING_APPROVAL may enter
it. An evidence-backed recovery claim may move RECOVERY_REQUIRED to RUNNING;
the Domain method creates a candidate only. The database must accept expected
status + updated_at before dispatch. Ordinary start/resume-approved transitions
do not reopen RECOVERY_REQUIRED.

RECOVERY_STALE_AFTER_SECONDS defaults to 300 in configuration and .env.example;
it must be positive and finite and can be changed for deployment. Task.updated_at
and execution updated_at are examined. Recent RUNNING Tasks or recent execution
activity are left alone. Staleness is evidence of inactivity, not proof a process
has died; this is not a heartbeat or lease system.

Classification uses fresh business reads and a Runtime WorkflowEvidence DTO
(checkpoint identity, next nodes, serialized values), with no active business
transaction across checkpoint inspection or execution:

| Durable facts | Action |
| --- | --- |
| WAITING_APPROVAL + matching PENDING Approval + approval_pause | NO_ACTION; no writes |
| Recent Task/execution activity | STILL_IN_PROGRESS; no dispatch |
| Stale RUNNING + matching APPROVED Approval + approval_pause | Claim then existing AgentRuntime.resume |
| Matching approved pending tool node | Claim then resume_pending_tool from the checked checkpoint |
| SUCCEEDED ledger | Existing approved execution returns cached result |
| Stale EXECUTING/UNKNOWN + NONE or missing Tool capability | RECOVERY_REQUIRED; no effect |
| Stale EXECUTING/UNKNOWN + EXTERNAL_KEY/INHERENT | One explicit ExecutionRecoveryService attempt |
| RUNNING + matching completed checkpoint and non-empty final answer | Conditional SUCCEEDED reconciliation; no LLM/Tool |
| Missing/incompatible checkpoint for waiting/stale active Task | Persist RECOVERY_REQUIRED; never invent initial input |
| Checkpoint without Task/Approval or incompatible terminal business state | ORPHAN_CHECKPOINT; never delete |

A healthy SUCCEEDED Task with matching completed checkpoint returns NO_ACTION.
A nonexistent Task without checkpoint also returns NO_ACTION. Existing FAILED and
REJECTED terminal Tasks are not reopened. Unsupported intermediate graph shapes
require operator review; this foundation is not a general graph recovery engine.

TaskRepository.reconcile_if_unchanged compares Task.id, expected status and exact
updated_at. A winning recovery claim advances updated_at strictly, even at equal
clock precision, and commits before dispatch. Losing requests do not dispatch.
Checkpoint identity is rechecked after claiming. A changed checkpoint suppresses
dispatch rather than overwriting workflow state. Completed-result reconciliation
uses the same conditional persistence and cannot overwrite a newer Task state.

TaskExecutionService captures a detached RUNNING snapshot before invoking the
continuation. All three lifecycle exits compare Task.id, RUNNING status and that
exact updated_at generation: FAILED, SUCCEEDED and WAITING_APPROVAL. A failed CAS
stops the old actor; it never falls back to an unconditional FAILED write. Pause
stages the generation check and new Approval in one transaction, rolling back the
Approval if ownership was lost. This also fences normal continuation writers
against a newer recovery owner while that owner is still RUNNING.

ExecutionRecoveryService retains Approval authorization and exact execution
context checks. It accepts only an existing stale EXECUTING/UNKNOWN identity with
explicit EXTERNAL_KEY or INHERENT capability. A conditional execution claim checks
UUID/status/updated_at and retains the same UUID/key, resets UNKNOWN to EXECUTING
for this one attempt and commits before external work. Shared execution mechanics
persist result/outcome. Normal and recovery result writes include their expected
claim timestamp, preventing an old writer from overwriting a newer recovery claim.
SUCCEEDED is subsequently consumed through the ordinary approved cache path.
No generic bypass is added to ApprovedToolExecutionService.

EXTERNAL_KEY recovery sends the same durable idempotency key. INHERENT relies on
the Tool's explicit idempotent semantics. NONE never re-executes an uncertain
operation. If recovery is again ambiguous, UNKNOWN remains in the ledger and
Task becomes RECOVERY_REQUIRED; no loop retries it. Recent repeated operator
requests cannot immediately trigger another attempt.

TaskRecoveryService reuses TaskResumeService/TaskExecutionService for completion,
known failures and subsequent approval pauses. Normal execution now maps
ToolExecutionOutcomeUnknown and ExecutionReplayBlocked to conditional
RECOVERY_REQUIRED rather than the old generic FAILED path. Known failures remain
FAILED. This necessary state-semantic change keeps uncertain executions eligible
for evidence-based recovery without reopening terminal failures. Historical
FAILED/REJECTED records are not automatically rewritten or retried.

ExecutionPersistenceUncertain is a local ledger persistence signal, distinct from
external ToolExecutionOutcomeUnknown and known execution failure. ExecutionRepository
wraps SQLAlchemy errors at claim/result commit acknowledgement boundaries and result
writes; the original database error remains the cause. TaskExecutionService stops
without writing FAILED or changing RUNNING on this signal. It does not infer whether
the database committed. Known input/provider/budget and explicit no-effect Tool
failures retain their failure contract; external ambiguity still requires recovery.
A fresh operator recovery reads Task, Approval, ledger and checkpoint evidence. A
committed SUCCEEDED ledger is consumed from cache, even when the original caller
received a commit error; a non-SUCCEEDED row still follows capability/staleness rules.

Recovery decisions use current durable truth, not the last caller's exception.
Tests commit APPROVED/RUNNING, lose acknowledgement, then recover with fresh runtime
and service based on the committed records. Result-commit uncertainty and missing
facts can still require another operator review. Timestamp claims are short
optimistic ownership checks, not durable liveness guarantees. The safety of an
EXTERNAL_KEY/INHERENT replay depends on the Tool/provider honoring that contract.
No universal exactly-once. No background automatic recovery.


## Structured Observability Foundation (TASK-031)

`app.observability` is a framework-neutral boundary with ObservabilityEvent,
ObservabilityContext, ObservabilitySink, StructuredLoggingSink and a thread-safe
InMemoryObservabilitySink for tests. Application services emit lifecycle facts;
repositories do not emit an event for each SQL operation. There is no event table,
backend exporter, metrics service or persistent audit log.

The version-one envelope always serializes event_name, UTC timestamp, level,
request_id, task_id, thread_id, approval_id, execution_id, tool_call_id, component,
outcome and attributes. Unavailable IDs are null. UUID identities serialize as
strings; ToolCall IDs are bounded identifier tokens. Event names, components and
outcomes have explicit accepted vocabularies. Events are validated before delivery;
both provided sinks serialize through the safe event boundary.

### Correlation and request isolation

| Field | Meaning |
| --- | --- |
| request_id | One HTTP request or top-level operator invocation |
| task_id | Primary AgentFlow business identity, stable across requests |
| thread_id | LangGraph workflow identity; explicitly set at the Runtime boundary |
| approval_id | Human authorization identity |
| execution_id | Protected Tool execution UUID, retained across safe recovery |
| tool_call_id | LLM ToolCall identity |

Task ID and workflow thread ID currently have equal UUID values but distinct
meanings. Task/Approval-only events need not carry thread_id. A new HTTP request
gets a server-generated UUID regardless of the client's X-Request-ID. Pure ASGI
RequestContextMiddleware wraps the complete FastAPI middleware stack, including
ServerErrorMiddleware, so normal, handled-error and generated 500 responses carry
X-Request-ID. WebSocket/lifespan scopes pass through without HTTP IDs.

ContextVar holds a frozen correlation context. Each HTTP scope starts fresh and
resets its token in finally. Nested application/Runtime scopes restore their parent;
operator service invocations create a request ID only if none exists. Context
crosses FastAPI worker and LangGraph execution boundaries without storing it in
business/checkpoint payloads. No traceparent or distributed tracing propagation is
implemented. Sink injection also uses a scoped ContextVar, allowing independent
capturing tests without replacing a global mutable sink.

### Event taxonomy and durable boundaries

| Events | Meaning / emission boundary |
| --- | --- |
| task.created | PENDING persistence returned successfully |
| task.state_changed | Accepted, committed lifecycle transition with from_status/to_status |
| task.completed | Confirmed SUCCEEDED, FAILED or REJECTED transition |
| approval.requested | Approval INSERT + generation-fenced WAITING_APPROVAL update committed |
| approval.decided | Atomic decision/Task claim or rejection committed, before resume dispatch |
| tool.execution.claimed | Normal or recovery ledger claim committed, before Tool execution |
| tool.execution.cache_hit | Authorized identity match reuses durable SUCCEEDED content |
| tool.execution.succeeded / failed / unknown | Terminal ledger write returned successfully |
| workflow.paused | Runtime received the graph interrupt after synchronous checkpoint writes |
| workflow.resumed | Authorized resume dispatch begins; not proof of eventual completion |
| recovery.started / completed | One operator invocation and its classification, or safe failed outcome |
| llm.request.started / succeeded / failed | One numbered attempt; success includes response validation |
| llm.retry.scheduled | Retry decision with the exact calculated delay before the existing sleep |

`task.state_changed` covers start rather than adding a redundant task.started.
RUNNING, WAITING_APPROVAL, SUCCEEDED, FAILED, REJECTED and RECOVERY_REQUIRED remain
observable. Recovery ownership claims can produce RUNNING -> RUNNING with a newer
business generation; this is not a second execution authorization mechanism.

Events follow acknowledged commits, never stage_save or an unaccepted conditional
write. Losing Task ownership emits no false success/failure/pause state transition.
A rollback emits no committed Approval request. A result-commit acknowledgement
loss may leave no success event even though the database committed; later recovery
can emit cache_hit based on fresh truth. Telemetry is neither a commit witness nor
a substitute for the Task/Approval/Execution/checkpoint sources of truth. There is
no atomic business-commit/event-delivery guarantee or global total ordering.

LLM events include configured model, one-based attempt, max_attempts and retryable
where relevant; scheduled retries include delay_seconds. Parsing is kept inside
the observable attempt, so invalid JSON/schema responses emit failed without a
success event and remain non-retryable. The existing retry count, exception contract,
exponential backoff, jitter calculation and sleep values are preserved.

### Safe attributes and best-effort delivery

Attributes use an allowlist with type/value checks, not a search for suspicious
keys. Allowed metadata: model, tool_name, idempotency_mode, argument_count,
from_status, to_status, status, decision, attempt, max_attempts, retryable,
delay_seconds, exception_type and fixed error_category. Unknown keys, nested payloads,
nonfinite numbers and non-serializable objects are dropped. String metadata is
bounded and constrained; identity/name fields must be content-free identifiers.
Never repurpose an allowed model/name/ID field to carry user content.

Defaults exclude Tool argument values and even argument_keys (keys can contain
sensitive text), Tool results, external bodies, raw checkpoints, HTTP bodies,
messages/prompts/document content, API keys, headers/cookies, base URLs and raw
exception strings. No ORM objects, Sessions, Tools or clients enter events.
The complete attributes dictionary is copied and sanitized; JSON output revalidates
it to prevent mutation from bypassing this policy. Arbitrary model_dump/payload
dictionaries are not valid telemetry contracts.

StructuredLoggingSink uses Python logging with a dedicated INFO logger and a
message-only StreamHandler: one event per JSON line, parseable with json.loads.
It does not reconfigure application/root logging. The emit boundary catches event
construction, serialization and sink failures without recursive fallback logging
or changing business state/results. Delivery is synchronous and best-effort;
there is no durable delivery, bounded sink latency, background worker or retention.
Future sinks must preserve privacy and failure isolation; an OTel sink/backend is
not part of this implementation.

## Migration qualification boundary (TASK-032)

Alembic autogeneration/check excludes only reflected tables owned by PostgresSaver:
checkpoints, checkpoint_blobs, checkpoint_writes and checkpoint_migrations. These
remain initialized by explicit `python -m app.workflows.setup`; their DDL is not
copied into historical/new AgentFlow migrations. The exclusion applies only when
no corresponding business metadata table exists. Unexpected tables and business
column drift still cause `alembic check` to fail, including unknown tables whose
names start with checkpoint_. Upgrade/downgrade of business migrations does not
own or delete the framework tables. Future PostgresSaver schema changes require
reviewing this explicit ownership list.


## Container and CI delivery boundary (TASK-033)

Compose gates backend startup on PostgreSQL health. The container entrypoint runs
the existing Alembic and PostgresSaver initialization commands sequentially before
execing Uvicorn as a non-root user. Initialization failures exit nonzero; FastAPI
import/lifespan retains its existing no-DDL contract. Repeated startup preserves
the separate schema ownership described above. This is a single-backend development
stack, not a multi-replica migration coordination or deployment architecture.

The HTTP health check establishes liveness after initialization, not continuing
DB/provider health. CI uses a separate PostgreSQL service and the same schema owner
commands, a zero-skips/zero-warnings pytest gate, and image build. Hosted CI evidence
and target deployment qualification remain separate release gates (ADR-010).


## Multi-Agent Layer boundary (TASK-036 and TASK-037 completed; TASK-038+ proposed)

This section records the current Agent Layer and the remaining future direction.
Agent Entity, AgentRegistry and AgentToolPolicy are established by TASK-036, and
the Agent Communication Contract is established by TASK-037. Supervisor
orchestration, routing, scheduling and software engineering tools remain
unimplemented. See [Multi-Agent Design](MULTI_AGENT_DESIGN.md) and
[ADR-011](DECISIONS.md#adr-011---multi-agent-architecture-direction).

Retain the application boundary:

```text
TaskExecutionService
  → Agent Layer (identity, role and policy description; non-executing)
    → Agent Communication Contract (message / artifact / future interaction schema)
      → existing AgentRuntime (single run / resume / recovery façade)
        → LangGraph Supervisor workflow (proposed, bounded and sequential)
          → Supervisor / Planner / Developer / Tester role nodes
            → existing Tool Runtime (proposed Agent Tool Policy at its entry points)
              → Execution Reliability Layer
```

Agent definitions describe identity, roles, prompts and policy metadata; they do
not own database Sessions, clients or execution lifecycles. Agent Entity,
AgentRegistry and AgentToolPolicy form a descriptive layer above AgentRuntime.
The Agent Communication Contract provides message and artifact schemas but does
not perform routing, scheduling, execution, persistence, approval or recovery.
The current AgentToolPolicy is not yet enforced by Tool Runtime. Future
Supervisor delegation is workflow routing, not a second business Tool execution
system or another AgentRuntime invocation.

Structured AgentMessage contracts carry selected inputs and results. Shared
checkpoint state carries workflow coordination data and references only; existing
Domain / Application Services retain business validation, authorization and
transaction ownership. A root Task retains its thread identity, while role
invocations have distinct correlation identities.

Role permissions are intersected with task/resource and deployment policy,
including normal execution, approved resume, cached result access and recovery.
side_effect_free remains an independent trusted Tool safety property. Safe tools
currently execute without Ledger rows; protected tools retain persisted Approval,
Execution Ledger and capability-aware recovery. All proposed write/test tools
must use that protected path. Human approval cannot override a permission denial.

The current recovery logic recognizes specific single-agent checkpoint shapes.
A future workflow needs explicit type/schema version selection, stable internal
operation IDs despite provider call-ID collisions, durable actor/operation
authorization binding, and compatible WorkflowEvidence before protected execution
is enabled. Checkpoint snapshots are never approval authority. Preserve
checkpoint-first pause, short business transactions, generation fencing and
UNKNOWN fail-closed semantics; no universal exactly-once guarantee is added.

Initial scope is one Supervisor and three sequential specialists, one outstanding
approval per root Task, and bounded rework. Nested runtimes, peer-to-peer routing,
parallel writes, extra execution ledgers and automatic recovery workers remain
outside the proposed first demo.


## TASK-037 — Agent Communication Contract (completed; PASS WITH NOTES)

The communication domain lives in `backend/app/agents/communication/`. It supplies
data contracts above AgentRuntime; it does not invoke Runtime, LLMs, Tools,
Approval, Ledger, Recovery or workflow code.

- AgentMessage: generated UUID message_id, required UUID task_id, nonblank string
  sender_agent_id / receiver_agent_id, MessageType, nonblank string content,
  tuple of Artifacts, JSON metadata and timezone-aware created_at normalized to UTC.
  Agent identifiers currently refer to Agent names; no registry lookup or identity
  authentication occurs. An explicitly supplied UUID supports reconstruction,
  but global uniqueness and delivery deduplication are not enforced.
- MessageType: REQUEST, RESPONSE, RESULT, ERROR, HANDOFF only. HANDOFF describes
  intent; it does not transfer control or schedule an Agent.
- Artifact: generated UUID artifact_id, ArtifactType (PLAN / CODE_PATCH /
  TEST_REPORT), nonblank name, required JSON content, and JSON metadata.
  Content is an inline generic payload, not a validated patch/test-report format.
  No storage URI, filesystem access or object store is implemented.
- Models reject unknown fields and invalid enum/UUID values. Fields are frozen;
  artifacts use a tuple. JSON payloads are defensively copied on construction,
  not deeply immutable. Payloads are untrusted data, never execution permission.
- CommunicationEvent is a future telemetry DTO with event_name, UTC timestamp,
  INFO level, agent component, task_id, message_id and optional request_id.
  Names are agent.message.sent, agent.message.received, agent.handoff.started.
  It excludes content, artifacts and arbitrary metadata. It follows TASK-031
  naming/correlation conventions but is NOT accepted by the existing
  ObservabilityEvent allowlist. No sink, adapter, event emission or Event Bus
  is added; constructing a DTO does not prove delivery.

Persistence boundary: in-memory runtime/domain objects only. No database tables,
message store, checkpoint integration, artifact persistence or delivery guarantees.
Supervisor, routing, scheduling, collaboration loops and Multi-Agent graphs remain
unimplemented; a later task may connect these contracts through the existing
Agent Layer → AgentRuntime boundary.

The current TASK-037 definition narrows earlier TASK-035 roadmap suggestions:
this task implements communication only; Supervisor work is reserved for TASK-038.
Advanced invocation/version/operation binding remains future design work. Earlier
design documents are proposals, not evidence these integrations exist.

Developer validation: 98 Agent Communication + Agent Abstraction tests passed.
Independent Review: PASS WITH NOTES; BLOCKER = 0; IMPORTANT = 0. Final project-state
synchronization is complete.


## TASK-038 — One-shot Supervisor delegation (awaiting Independent Review)

Implemented in `backend/app/agents/supervisor.py`: create_supervisor returns the
existing Agent with role SUPERVISOR; select_worker resolves an exact configured
name (default developer) from AgentRegistry and requires role DEVELOPER.
delegate_task is a synchronous one-shot orchestration function, not a Runtime,
executor, scheduler or graph. There is no model call for Supervisor decision making.

```text
Caller owning Task lifecycle / Runtime resources
  → delegate_task with Supervisor Agent and existing AgentRegistry
  → REQUEST AgentMessage
  → injected existing AgentRuntime.run(worker system prompt + request content)
  → existing LangGraph / existing Tool safety path
  → RESULT AgentMessage returned to Supervisor
```

The same business task_id is passed unchanged. RESULT reverses sender/receiver and
contains metadata.in_reply_to referencing the REQUEST UUID. DelegationResult exposes
both messages to the caller. No artifacts are inferred from plain Runtime output.
An invalid role, missing worker, self-delegation or invalid request fails before
Runtime invocation. Runtime exceptions, including ApprovalRequired, propagate
unchanged; no RESULT is synthesized on pause/error, no retry/resume/close occurs.

The caller must provide an existing managed Task and properly configured Runtime.
This entry point is not wired to TaskExecutionService or HTTP; it does not create
Task rows, claim lifecycle transitions or handle durable delegation resume.
The existing Runtime owns execution and protected-tool safety. Role allowed_tools
remains declarative: this MVP does not enforce per-Agent grants against Runtime
tools. An unrestricted Runtime must not be presented as isolated worker execution.
Tests use an empty ToolRegistry for the real Runtime smoke path.

CommunicationEventName adds agent.delegation.started / completed as future DTO
vocabulary only. No event is emitted; the existing TASK-031 allowlist/sinks remain
unchanged. REQUEST/RESULT messages are in memory, with no restart reconstruction,
deduplication or durable completion envelope after approval resume.

The explicit TASK-038 definition selects an above-Runtime rule-based MVP instead
of implementing the earlier TASK-035 graph-internal Supervisor proposal.
See ADR-012. No new execution system, LangGraph modification, scheduling, planner,
autonomous loop, message persistence, queue or complex workflow is introduced.
Developer validation: 14 TASK-038 tests passed; Independent Review pending.

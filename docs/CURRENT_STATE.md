# AgentFlow-AI Current State

This file is intentionally high-frequency and describes repository-confirmed status only.

本文只记录仓库中已经确认的状态。未验证的代码、未运行的测试和聊天中的计划不得写成已完成。

## Current Phase / 当前阶段

Phase 1 - Core Agent Runtime

## Current Milestone / 当前里程碑

Establish the project foundation and complete the first runnable FastAPI backend.

中文释义：当前首先要形成清晰的项目骨架和最小可运行服务，再逐步接入 LLM 与 Agent Runtime。

## Process / Infrastructure

* Workspace Boundary Guard v1 established

当前 Guard 属于 Soft / Process Guard，不是操作系统级 Hard Filesystem Sandbox。

## Completed / 已完成

* project scope defined
* initial architecture defined
* roadmap defined
* long-term AI development documentation system established
* AI handoff context system established
* TASK-001 - Minimal FastAPI Application
* FastAPI application established
* `/api/health` endpoint implemented and independently verified
* automated API tests established
* TASK-002 - First LLM Client Abstraction
* LLM configuration established
* typed chat message schema established
* OpenAI-compatible LLM client implemented
* provider HTTP and invalid response errors handled
* LLM client tests independently verified
* TASK-003 - Tool Abstraction and Tool Registry
* Tool contract established
* validated Tool input schema established
* ToolResult established
* ToolRegistry implemented
* CalculatorTool implemented
* Tool Registry tests independently verified
* TASK-004 - Tool Calling Integration
* provider-neutral `ToolCall` model established
* OpenAI-compatible tool schema adapter implemented
* `LLMClient` supports optional tool definitions
* provider tool call parsing implemented
* `ToolExecutor` implemented
* Calculator Tool Call integration independently verified
* 26 tests passed
* TASK-005 - Minimal Agent Execution Loop
* `AgentRuntime` established
* bounded Agent Loop implemented
* Tool results reintroduced into conversation history
* multi-round Tool Calling supported
* multiple Tool Calls per LLM response supported
* `max_steps` execution boundary established
* final answer contract established
* 40 tests passed
* TASK-006 - Agent API Integration
* synchronous Agent API established
* POST /api/agent/run exposed
* request/response contracts established
* API → AgentRuntime boundary established
* safe domain error mapping implemented
* process-level shared AgentRuntime lifecycle established
* LLMClient HTTP resource ownership clarified
* thread-safe lazy initialization implemented
* 57 tests passed
* TASK-007 - Task State Foundation
* Task domain entity established
* UUID task identity established
* Task state machine established
* explicit lifecycle methods implemented
* domain invariants enforced
* lifecycle-related public mutation protected
* UTC timestamp contract established
* monotonic updated_at enforced
* 99 tests passed
* TASK-008 - PostgreSQL Task Persistence
* PostgreSQL Task persistence established
* SQLAlchemy persistence layer established
* Domain / ORM separation established
* TaskRepository save/get implemented
* controlled Task rehydration established
* Alembic migration established
* transaction boundary and rollback semantics verified
* real PostgreSQL integration verified
* 114 tests passed
* TASK-009 - Task Execution Integration
* TaskExecutionService established
* persistent Agent task lifecycle established
* PENDING → RUNNING → SUCCEEDED / FAILED orchestration implemented
* API now delegates execution orchestration to TaskExecutionService
* request-scoped SQLAlchemy Session lifecycle established
* AgentRuntime process-level reuse preserved
* Agent failure persistence implemented
* primary / secondary failure priority contract established
* best-effort lifecycle persistence contract documented
* TASK-010 - Task Query API
* single Task Query API established
* GET /api/tasks/{task_id}
* Repository boundary preserved
* independent API Response DTO established
* UUID / status / timestamp serialization verified
* missing Task returns 404
* invalid UUID returns 422
* safe FAILED task response verified
* 115 runnable tests passed in current environment
* TASK-011 - Expose Task ID from Agent Run
* Agent Run response now exposes persistent task_id
* task_id originates from the real Domain Task
* AgentRunResponse DTO established
* POST /api/agent/run → task_id → GET /api/tasks/{task_id} resource closure established
* existing failure mapping preserved
* query API regression verified
* 116 runnable tests passed in current environment
* TASK-012 - Task Listing API
* Task listing API established
* GET /api/tasks
* offset pagination established
* limit / offset validation established
* deterministic ordering established with created_at DESC, id DESC
* TaskRepository collection query established
* TaskListResponse established
* Domain / DTO boundary preserved
* 123 runnable tests passed in current environment
* TASK-013 - Task Status Filtering
* optional task status filtering established
* GET /api/tasks?status=...
* SQL-level status filtering established
* supported values: pending / running / succeeded / failed
* filter + deterministic ordering + pagination composition verified
* invalid status returns 422
* TaskRepository collection query extended without breaking default listing
* 128 runnable tests passed in current environment
* TASK-014 - Reliability Foundation / LLM Request Timeout Foundation
* TASK-014 review result: PASS WITH NOTES
* explicit configurable LLM timeout established
* per-request httpx timeout applied
* TimeoutException mapped to LLMProviderError
* LLM client ownership preserved
* retry not yet implemented
* 132 tests passed
* TASK-015 - LLM Failure Classification Foundation
* TASK-015 review result: PASS WITH NOTES
* LLMProviderError.retryable established
* timeout/network → retryable
* 429/5xx → retryable
* 4xx/default → non-retryable
* no automatic retry
* 140 passed, 24 skipped, 1 warning
* TASK-016 - Bounded LLM Retry Policy
* TASK-016 review result: PASS WITH NOTES
* LLM_MAX_ATTEMPTS established with bounded provider retry
* retryable=True controls retry
* non-retryable failures fail fast
* attempt exhaustion preserves final failure
* Agent/Task lifecycle unaffected
* 147 passed, 24 skipped, 1 warning
* TASK-017 - LLM Retry Timing Policy
* TASK-017 review result: PASS WITH NOTES
* configurable retry base delay established
* exponential backoff established
* bounded additive jitter established
* injectable sleeper/jitter for deterministic tests
* no final-attempt sleep
* Agent/Task lifecycle unaffected
* 147 passed, 24 skipped, 1 warning
* TASK-018 - Tool Execution Safety Metadata Foundation
* TASK-018 review result: PASS WITH NOTES
* ToolMetadata.side_effect_free established
* safe default=False established for unknown and unannotated tools
* Calculator side_effect_free=True established
* Tool Registry metadata preservation verified
* provider schema isolation preserved
* ToolExecutor behavior unchanged
* 151 passed, 24 skipped, 1 warning
* TASK-019 - Side-effect Tool Execution Guard
* TASK-019 review result: PASS WITH NOTES
* ToolExecutionPolicy established at the ToolExecutor boundary
* fail-closed side-effect guard established
* trusted internal safety metadata used for policy decisions
* rejection occurs before Tool.execute()
* unknown and unannotated tools rejected by default
* AgentRuntime remains policy-agnostic
* 153 passed, 24 skipped, 1 warning
* TASK-020 - Approval Domain Model Foundation
* TASK-020 review result: PASS WITH NOTES
* independent Approval domain entity established
* ApprovalStatus PENDING / APPROVED / REJECTED established
* terminal transition protection established
* UTC timestamps and ToolCall association established
* new Approval creation separated from restore / rehydration
* Approval Persistence Readiness = Ready
* 171 passed, 24 skipped, 1 warning
* TASK-021 - Approval Persistence Foundation
* TASK-021 review result: PASS WITH NOTES
* Approval ORM / Domain separation established
* ApprovalRepository create / get_by_id / save established
* Approval.restore rehydration established
* PostgreSQL UUID / JSONB / FK persistence established
* Alembic migration 0002 established
* real PostgreSQL verification completed
* Approval Persistence Readiness = Ready
* 204 passed, 0 skipped, 1 warning
* TASK-022 - Protected Tool Execution Request Foundation
* TASK-022 review result: PASS WITH NOTES
* ProtectedToolExecutionService established as the protected execution orchestration boundary
* safe Tools execute exactly once without creating Approval
* registered side-effectful and unannotated Tools create persistent PENDING Approval requests
* ApprovalRequired carries persisted approval identity and protected ToolCall context
* protected Tool rejection occurs before Tool.execute(), including persistence failure paths
* unknown Tools remain ToolNotFoundError paths without creating Approval
* HITL Pause Integration Readiness = Ready
* 210 passed, 0 skipped, 1 warning
* TASK-023 - HITL Pause Integration Foundation
* TASK-023 review result: PASS WITH NOTES
* WAITING_APPROVAL lifecycle state established from RUNNING
* AgentRuntime wired to ProtectedToolExecutionService
* ApprovalRequired reaches TaskExecutionService unchanged
* atomic Approval(PENDING) + Task(WAITING_APPROVAL) pause persistence established
* conditional RUNNING → FAILED persistence protects committed WAITING_APPROVAL
* Approval Decision Integration Readiness = Ready
* 245 passed, 0 skipped, 1 warning
* TASK-024 - Approval Decision Integration Foundation
* TASK-024 review result: PASS WITH NOTES
* Approval Decision API established for approve / reject
* ApprovalDecisionService established
* PENDING → APPROVED / REJECTED decision flow established
* atomic conditional decision persistence established
* concurrent decisions have a single-winner guarantee
* Task eligibility requires WAITING_APPROVAL
* Task remains WAITING_APPROVAL after decision
* approved decision does not execute Tool
* Approval Lifecycle Integration Readiness = Ready
* 258 passed, 0 skipped, 1 warning

上述项目基础、TASK-001、TASK-002、TASK-003、TASK-004、TASK-005、TASK-006、TASK-007、TASK-008、TASK-009、TASK-010、TASK-011、TASK-012、TASK-013、TASK-014、TASK-015、TASK-016、TASK-017、TASK-018、TASK-019、TASK-020、TASK-021、TASK-022、TASK-023 和 TASK-024 已经过实现、测试及 Independent Review 验证。

## In Progress / 进行中

None currently confirmed.

## Known Issues / 已知问题

已确认的维护事项记录在 `docs/TECH_DEBT.md`：

* TD-001 - TestClient dependency deprecation warning
* TD-002 - Backend working-directory dependency
* TD-004 - Calculator accepts non-finite and boolean numeric inputs
* TD-005 - Alembic configuration coupled to LLM application settings

## Next / 下一步

Approval Decision → Task Lifecycle Integration

Status: Not Started

Approval decision 已建立，但尚未实现 decision 后的 Task lifecycle continuation。当前尚未定义为具体 Task，暂不开始执行。

# AgentFlow-AI Current State

This file is intentionally high-frequency and describes repository-confirmed status only.

本文只记录仓库中已经确认的状态。未验证的代码、未运行的测试和聊天中的计划不得写成已完成。

## Current Phase / 当前阶段

Phase 1 - Core Agent Runtime

## Current Milestone / 当前里程碑

Core runtime, real Provider HTTP E2E validation, delivery qualification and final project packaging established.

中文释义：项目核心 Runtime、真实 Provider HTTP E2E、交付 qualification 与最终项目文档已完成；生产部署和生产级 Provider qualification 仍属可选后续验收。

## Project Development Status / 项目开发状态

Completed / Finalized

Core runtime, reliability, delivery qualification and final project packaging are complete.
Real LLM Provider HTTP E2E validation is complete in the development environment.
Production Deployment Qualification and production-grade Provider Qualification remain outside the validated scope.

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
* TASK-025 - Approval Decision to Task Lifecycle Integration
* TASK-025 review result: PASS WITH NOTES
* TaskStatus.REJECTED established
* WAITING_APPROVAL → REJECTED transition established
* REJECTED kept distinct from FAILED
* atomic Approval rejection + Task rejection established
* approve remains APPROVED + WAITING_APPROVAL
* approve/reject cross-entity concurrency protection verified
* status=rejected filtering established
* decision paths do not execute Tool
* Resume Architecture Readiness = Ready
* 277 passed, 0 skipped, 1 warning
* TASK-026 - LangGraph Durable Workflow Foundation
* TASK-026 review result: PASS
* Incremental LangGraph adoption established
* ADR-005 recorded
* minimal StateGraph and AgentGraphState established
* AgentFlow Task.id → LangGraph configurable.thread_id contract established
* PostgreSQL-backed PostgresSaver and explicit checkpoint schema setup established
* durable interrupt and Command(resume=...) continuation established
* cross-process checkpoint recovery with fresh Saver + fresh Graph verified
* resume without re-submitting initial workflow input verified
* thread isolation verified
* 285 passed, 0 failed, 0 skipped, 0 warnings
* TASK-027 - AgentRuntime → LangGraph Orchestration Integration
* TASK-027 review result: PASS
* AgentRuntime orchestration migrated to LangGraph StateGraph
* AgentRuntime remains application-facing façade
* LLM node, Tool node and conditional routing established
* multiple ToolCalls and multi-round Tool Calling preserved
* existing max_steps semantics preserved
* existing final answer and error behavior preserved
* ApprovalRequired propagation preserved
* real Agent PostgreSQL checkpoint integration not yet established
* 293 passed, 0 failed, 0 skipped, 0 warnings
* TASK-028 - Approved Tool Resume Integration
* TASK-028 review result: PASS
* real Agent Graph uses PostgreSQL-backed durable checkpoints
* checkpoint-first protected Tool pause through a separate replay-safe interrupt node established
* Approval PENDING + Task WAITING_APPROVAL → Approval APPROVED + Task RUNNING atomic continuation claim established
* TaskResumeService established
* fresh Runtime / Graph / Saver resume established
* persisted Approval is the authorization Source of Truth
* approved protected Tool continuation established
* Tool cursor prevents replay of completed ToolCalls
* multiple sequential Approvals supported
* normal approval concurrency remains single-winner
* no crash-safe exactly-once guarantee established
* 318 passed, 0 failed, 0 skipped, 0 warnings
* TASK-029 - Protected Tool Idempotency / Execution Ledger
* TASK-029 review result: PASS
* Protected Tool Execution Ledger established
* independent execution UUID and stable idempotency_key established
* UNIQUE(task_id, tool_call_id) business uniqueness established
* EXECUTING / SUCCEEDED / FAILED / UNKNOWN ledger states established
* database-enforced single-winner execution claim established
* SUCCEEDED replay reuses durable result without re-executing the Tool
* UNKNOWN and EXECUTING fail closed
* persisted Approval remains authorization Source of Truth
* Tool idempotency capability contract established: NONE / EXTERNAL_KEY / INHERENT
* tool_executions business table managed by Alembic
* no universal crash-safe exactly-once guarantee
* 344 passed, 0 failed, 0 skipped, 0 warnings
* TASK-030 - Resume Reliability / Recovery
* Initial Independent Review: FAIL with 2 IMPORTANT findings
* Focused Fix completed; Focused Re-Review: PASS
* both original IMPORTANT findings closed
* RECOVERY_REQUIRED Task state and operator-triggered recovery established
* TaskRecoveryService and evidence-driven Task/Approval/checkpoint/ledger reconciliation established
* database single-winner recovery claim and generation-fenced lifecycle writes established
* SUCCEEDED cached recovery and completed Graph reconciliation established
* stale EXECUTING / UNKNOWN recovery follows capability-aware policy
* persistence acknowledgement uncertainty separated from known execution failure
* missing checkpoint and orphan checkpoint detection established without deletion
* no background automatic recovery or universal crash-safe exactly-once guarantee
* 384 passed, 0 failed, 0 skipped, 0 warnings
* TASK-031 - Observability Foundation
* TASK-031 review result: PASS
* framework-neutral ObservabilityEvent / Context / Sink boundary established
* StructuredLoggingSink JSON structured logs established
* server-generated request_id and X-Request-ID response propagation established
* request isolation through ContextVar reset established
* task_id primary cross-request business correlation established
* thread_id / approval_id / execution_id / tool_call_id correlation established
* 18 lifecycle events across Task, Approval, Tool Execution, Workflow, Recovery and LLM reliability established
* sensitive-data allowlist policy established
* Tool arguments, results, prompts, messages and raw exception strings excluded by default
* best-effort telemetry established; sink failure does not affect business semantics
* event truthfulness respects transaction, generation and commit-uncertainty boundaries
* no metrics backend, distributed tracing backend or persistent audit log
* 417 passed, 0 failed, 0 skipped, 0 warnings
* TASK-032 - Project Hardening & End-to-End Validation
* TASK-032 review result: PASS WITH NOTES
* Application Core = PASS
* Engineering Reproducibility = PASS
* Plain Assistant, Safe Tool, Protected HITL Approve/Reject and Cached Replay E2E verified
* stale recovery, UNKNOWN fail-closed behavior and completed checkpoint reconciliation verified
* cross-request observability correlation and zero sensitive marker leakage verified
* Alembic business schema and LangGraph checkpoint schema ownership hardened
* invalid ToolCall restored to safe HTTP 502 / Task FAILED behavior
* fresh Python 3.11 venv and PostgreSQL 17 reproducibility verified
* 432 passed, 0 failed, 0 skipped, 0 warnings
* Container Delivery = Not Yet Qualified
* CI Automation = Not Yet Qualified
* Deployment Qualification = Not Yet Qualified
* application-level release qualification completed; delivery automation and deployment qualification remain pending
* TASK-033 - Container & CI Delivery Qualification
* TASK-033 review result: PASS
* Application Core = Qualified
* Engineering Reproducibility = Qualified
* Container Delivery = Qualified
* Python 3.11 non-root backend image and PostgreSQL 17 Compose stack qualified
* TCP PostgreSQL healthcheck and backend dependency on database health qualified
* Alembic then PostgresSaver dual-schema startup and fail-fast initialization qualified
* fresh-volume startup, restart and API smoke qualified
* CI Workflow = Qualified
* Local Independent CI Reproduction = PASS
* GitHub-hosted CI Run = PASS
* CI gate rejects test skips, collection skips and warnings
* Post-Push Hosted CI Gate = PASS
* Hosted CI Qualification = PASS
* CI Automation = Qualified
* Deployment Qualification = Not Yet Qualified
* no production-ready or production-qualified claim
* 440 passed, 0 failed, 0 skipped, 0 warnings
* TASK-034 - Final Project Packaging
* TASK-034 review result: PASS
* final README, resume, interview guide and project report completed
* three Mermaid architecture/workflow diagrams and Capability Matrix completed
* Technology Selection, Reliability / Safety Story and Known Boundaries documented
* Application Core = Qualified
* Engineering Reproducibility = Qualified
* Container Delivery = Qualified
* CI Automation = Qualified
* GitHub-hosted CI = PASS
* Final Project Packaging = Qualified
* Deployment Qualification = Not Yet Qualified
* Real Provider Validation = Not Yet Qualified at the TASK-034 packaging checkpoint; superseded by the subsequent Real LLM HTTP E2E validation
* 3/3 Mermaid diagrams parsed, 6/6 PowerShell blocks parsed, 23 local Markdown links valid
* Compose configuration valid

## Real LLM / HTTP E2E Validation / 真实 LLM / HTTP E2E 验证

* Real LLM Provider integration = Validated in development environment
* OpenAI-compatible HTTP path to DeepSeek validated
* Real Tool Calling = Validated
* AgentRuntime + LangGraph real E2E = Validated
* FastAPI `POST /api/agent/run` real HTTP E2E = Validated
* PostgreSQL Task persistence and subsequent Task query = Validated
* Developer evidence: focused 46 passed and full 440 passed, 0 failed, 0 skipped, 0 warnings
* Reviewer evidence: 44 passed, 0 failed, 0 skipped, 0 warnings; real DeepSeek call not repeated
* Review Result: PASS WITH NOTES; BLOCKER = 0; IMPORTANT = 0
* DeepSeek is the validated development Provider, not an architecture binding

上述项目基础、TASK-001、TASK-002、TASK-003、TASK-004、TASK-005、TASK-006、TASK-007、TASK-008、TASK-009、TASK-010、TASK-011、TASK-012、TASK-013、TASK-014、TASK-015、TASK-016、TASK-017、TASK-018、TASK-019、TASK-020、TASK-021、TASK-022、TASK-023、TASK-024、TASK-025、TASK-026、TASK-027、TASK-028、TASK-029、TASK-030、TASK-031、TASK-032、TASK-033 和 TASK-034 已经过实现、测试及 Independent Review 验证。

## In Progress / 进行中

None currently confirmed.

## Known Issues / 已知问题

已确认的维护事项记录在 `docs/TECH_DEBT.md`：

* TD-001 - TestClient dependency deprecation warning
* TD-002 - Backend working-directory dependency
* TD-004 - Calculator accepts non-finite and boolean numeric inputs
* TD-005 - Alembic configuration coupled to LLM application settings

## Next / 下一步

None / Project Complete

Status: Completed / Finalized

主开发路线已在 TASK-034 收敛。不存在 active next Task，也不创建 TASK-035。

Optional Future Work：Deployment Qualification、production-grade Provider Qualification、OpenTelemetry backend、Metrics / dashboards、Worker / Queue、Multi-Agent、MCP。

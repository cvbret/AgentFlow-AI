# AgentFlow-AI Roadmap

This roadmap is directional. A phase is not considered complete merely because its topic appears here; completion requires implementation, tests, review, and synchronized project state.

中文释义：路线图描述推进顺序，不代表功能已经存在。阶段完成必须有可验证的代码和测试，并同步更新项目状态。

## Phase 1 - Core Agent Runtime / 核心 Agent Runtime

* project skeleton
* FastAPI application
* LLM client
* single tool
* tool calling
* minimal agent loop

先建立最小可运行后端，理解 LLM、工具和循环之间的真实边界。

## Phase 2 - Tool System / 工具系统

* Tool abstraction
* Tool schema
* Tool Registry
* Tool Dispatcher
* input validation
* tool error handling

把工具从单个实现提升为可注册、可校验、可分发的明确系统。

## Phase 3 - Task State / 任务状态

* Task model
* execution steps
* PostgreSQL persistence
* task lifecycle
* execution history

建立 durable task state，并明确 PostgreSQL 作为持久任务和历史记录的 Source of Truth。

## Phase 4 - Reliability / 可靠性

* maximum execution steps
* timeout
* retries
* error classification
* idempotency
* side-effect control

让 Agent 在失败、慢响应和重复执行场景下仍有可预测边界。

## Phase 5 - Workflow / 工作流

* explicit workflow states
* conditional transitions
* workflow execution
* LangGraph evaluation completed by TASK-026
* incremental LangGraph adoption selected
* AgentRuntime orchestration integration completed by TASK-027
* Approved Tool Resume integration completed by TASK-028
* Protected Tool Idempotency / Execution Ledger completed by TASK-029
* Resume Reliability / Recovery completed by TASK-030

LangGraph evaluation was intentionally deferred until an actual workflow-orchestration requirement appeared. That evaluation completed in TASK-026, and incremental adoption was selected; LangGraph remains not a Day 1 mandatory dependency.

中文释义：先用显式状态和转移表达真实需求，再评估框架是否减少复杂度。不能因为路线图提到 LangGraph，就提前把它加入初始 Runtime。

TASK-031：Observability Foundation 已完成。

TASK-032：Project Hardening & End-to-End Validation 已完成。

TASK-033：Container & CI Delivery Qualification 已完成。

TASK-034：Final Project Packaging 已完成。

Real LLM HTTP E2E Integration：真实 OpenAI-compatible Provider、Tool Calling、AgentRuntime、FastAPI HTTP 与 PostgreSQL Task persistence 已完成开发环境验证。

AgentFlow-AI Core Project = Completed / Finalized。

原 Core Project roadmap 在 TASK-034 完成收尾；TASK-035 作为 Multi-Agent 架构研究任务保留其既有状态。TASK-036 Agent Abstraction Layer、TASK-037 Agent Communication Model 与 TASK-038 Supervisor Orchestration 已完成，TASK-039 Tool Permission Enforcement 已完成，TASK-040 Multi-Agent HITL Integration 已完成，TASK-041 按明确 Task Definition 推进。

Optional Future Work：Deployment Qualification、production-grade Provider Qualification、OpenTelemetry backend、Metrics / dashboards、Worker / Queue、MCP。

## Phase 6 - Observability / 可观测性

* structured logging foundation completed by TASK-031
* tracing backend remains future capability
* metrics backend remains future capability
* persistent audit history remains future capability

TASK-032 已完成 application-level release qualification；TASK-033 已完成 Docker delivery 与 CI automation qualification，deployment qualification 仍未完成。

TASK-033 已完成 Container Delivery qualification 与 GitHub-hosted CI qualification；Deployment Qualification 仍待完成。

## Phase 7 - Human in the Loop / 人在回路

* approval steps
* dangerous tool confirmation
* pause / resume
* Approval / Protected Tool Resume integration follows TASK-027
* Approved Tool Resume integration completed by TASK-028
* Protected Tool Idempotency / Execution Ledger completed by TASK-029

## Phase 8 - Multi-Agent / 多 Agent

Later evaluation may include:

* Planner
* Executor
* Reviewer

多 Agent 放在后期，是因为它会同时扩大状态管理、通信、故障隔离和审计范围；应建立可靠的 Single-Agent Runtime 后再评估。


## TASK-035+ — Multi-Agent Extension

TASK-035 架构研究及设计交付已完成；ADR-011 仍为 Proposed，不据此宣称其已 Accepted。
TASK-036 Agent Abstraction Layer、TASK-037 Agent Communication Model 与 TASK-038
Supervisor Orchestration 已完成并通过 Independent Review，Review Result 均为
**PASS WITH NOTES**；TASK-039 已 Completed，Independent Re-Review #2 = PASS WITH NOTES；TASK-040 为 **Completed / PASS WITH NOTES**；TASK-041 为 **Not Started**，不改变既有
Core Project qualification。后续实施以 ADR-011 审查和各 Task 的明确范围为前提。

方向：[Multi-Agent Design](MULTI_AGENT_DESIGN.md) /
[ADR-011](DECISIONS.md#adr-011---multi-agent-architecture-direction)。

| Task | Planned scope | Dependency / exit gate |
| --- | --- | --- |
| TASK-036 — Agent abstraction | Agent Entity、静态 AgentRegistry、声明性 AgentToolPolicy；不负责执行，不引入第二套 Agent Runtime | 已完成；Independent Review = PASS WITH NOTES；85 tests passed |
| TASK-037 — Agent Communication Model | AgentMessage、MessageType、Artifact 与未来 CommunicationEvent contract；不负责 routing、scheduling、execution 或 persistence | 已完成；Independent Review = PASS WITH NOTES；98 related tests passed |
| TASK-038 — Supervisor Orchestration | Agent(role=SUPERVISOR)、固定 Developer 路由、REQUEST/RESULT、一次注入的既有 AgentRuntime 调用 | 已完成；Independent Review = PASS WITH NOTES；14 tests passed；无 Scheduling/Planner/复杂 workflow |
| TASK-039 — Tool Permission Enforcement | 既有 Tool boundary exact allow-list enforcement、durable identity continuity、ambiguous provenance fail closed | Completed；PASS WITH NOTES；两个 IMPORTANT Closed；Reviewer 196 passed / 0 failed / 0 skipped / 0 warnings |
| TASK-040 — Multi-Agent HITL Integration | Supervisor 委派接入既有 durable HITL；fresh Worker identity、权限复查、Ledger/recovery 与结果关联 | 039；Completed；PASS WITH NOTES；Reviewer 183 passed / 0 failed / 0 skipped / 0 warnings |
| TASK-041 — Multi-Agent Demo Packaging | AI Software Engineering Assistant fixture、演示说明、配置和架构图、CI 回归与成本质量证据 | 040；Not Started；独立 Review 后再同步项目状态 |

所有未来任务继续复用 TaskExecutionService → AgentRuntime → LangGraph Workflow →
Tool Runtime，不引入第二套 executor、审批存储或 Agent-owned DB lifecycle。
首版不含 peer-to-peer、多层团队、并行写入、多个 pending approvals、worker/queue。
工具权限配置不等于 OS sandbox；生产认证、部署和持久审计仍需独立 qualification。


TASK-039 已完成 Tool Runtime exact allow-list enforcement 与 durable Agent identity
continuity。Runtime 恢复 checkpoint provenance，Tool 层做权限决策。仅 explicit
LEGACY continuation 兼容；AGENT_BOUND 恢复可信身份并执行策略；missing/null/unknown
或不一致 provenance fail closed。历史 ambiguous checkpoint 需 trusted migration，
通用 migration tooling 未实现。enterprise authorization、dynamic policy 与
user-level permission 不在范围内。TASK-040 已完成并通过 Independent Review（PASS WITH NOTES；BLOCKER = 0；IMPORTANT = 0）。唯一 NOTE 为结果投影的独立只读 Session contract。TASK-041 Not Started。受控工程 Tool 扩展未在本任务实现，需后续明确 Task scope。

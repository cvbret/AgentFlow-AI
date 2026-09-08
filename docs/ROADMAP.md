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
* AgentRuntime orchestration integration

LangGraph evaluation was intentionally deferred until an actual workflow-orchestration requirement appeared. That evaluation completed in TASK-026, and incremental adoption was selected; LangGraph remains not a Day 1 mandatory dependency.

中文释义：先用显式状态和转移表达真实需求，再评估框架是否减少复杂度。不能因为路线图提到 LangGraph，就提前把它加入初始 Runtime。

## Phase 6 - Observability / 可观测性

* structured logging
* tracing
* metrics
* audit history

## Phase 7 - Human in the Loop / 人在回路

* approval steps
* dangerous tool confirmation
* pause / resume

## Phase 8 - Multi-Agent / 多 Agent

Later evaluation may include:

* Planner
* Executor
* Reviewer

多 Agent 放在后期，是因为它会同时扩大状态管理、通信、故障隔离和审计范围；应建立可靠的 Single-Agent Runtime 后再评估。

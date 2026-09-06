你现在负责继续开发项目：

`AgentFlow-AI`

Repository root：

`E:\AIProjects\AgentFlow-AI`

本次任务：

`TASK-014 - Reliability Foundation / LLM Request Timeout Foundation`

请使用中文回复所有：

* 工作计划
* Planned Write Set
* Completion Report
* 问题说明
* 风险说明

代码、路径、class/function 名称、测试名称和英文工程术语可以保留英文。

---

## 0. Workspace Boundary Guard

在进行任何写操作前，必须先执行并确认：

```powershell
Get-Location
git rev-parse --show-toplevel
```

Git root 必须是：

```text
E:\AIProjects\AgentFlow-AI
```

如果不是该路径：

立即停止，不进行任何写操作，并报告问题。

所有写入必须位于：

```text
E:\AIProjects\AgentFlow-AI
```

Repository 内。

优先使用 repository-relative path。

如果某个工具技术上必须使用 absolute path，只允许使用已经确认 containment 的 repository-internal absolute path。

任何 repository 外写入都视为 Workspace Guard violation，必须立即报告，不允许自行隐藏、删除后继续。

写操作前先报告：

```text
Planned Write Set
```

---

## 1. Context Loading

Repository 是 Source of Truth。

不要依据旧聊天记录猜测当前实现。

首先阅读：

```text
docs/PROJECT.md
docs/CURRENT_STATE.md
docs/AI_HANDOFF.md
AGENTS.md
```

然后阅读与本任务直接相关的：

```text
docs/ROADMAP.md
docs/TECH_DEBT.md
docs/ARCHITECTURE.md
docs/DECISIONS.md
```

以及：

```text
现有 LLMClient
LLM configuration
LLM exception/error definitions
AgentRuntime
TaskExecutionService
relevant tests
```

如存在：

```text
tasks/TASK-014.md
```

则先阅读。

如果不存在，需要根据本 Prompt 与 repository 当前事实创建最小、聚焦的 TASK-014 specification。

不要为了获取上下文而读取整个 repository。

---

# 2. 当前项目背景

当前阶段：

```text
Phase 1 - Core Agent Runtime
```

最新完成：

```text
TASK-013 - Task Status Filtering
```

当前 AgentFlow-AI 已具备：

```text
FastAPI
LLM Client abstraction
Tool abstraction
Tool Registry
Tool Executor
Calculator Tool

LLM
→ Tool Call
→ Tool Execution
→ Tool Result
→ LLM
→ Final Answer

bounded Agent loop
multiple tool calls
multi-round tool calling
max_steps

Task Domain
TaskStatus
TaskRepository
PostgreSQL
SQLAlchemy
Alembic

TaskExecutionService

POST /api/agent/run
GET /api/tasks/{task_id}
GET /api/tasks
Task pagination
Task status filtering
```

Durable Task State 的 Source of Truth 当前为 PostgreSQL。

Task lifecycle：

```text
PENDING
→ RUNNING
→ SUCCEEDED / FAILED
```

TASK-009 已经建立 failure semantics：

```text
Primary Failure
=
Agent execution failure

Secondary Failure
=
FAILED lifecycle persistence failure
```

Secondary persistence failure 不允许覆盖 Primary Agent error。

---

# 3. Existing Technical Debt

当前存在：

```text
TD-003
LLM HTTP timeout is not explicitly configured / 尚未形成明确项目级 Reliability contract
```

TASK-014 的核心目标就是开始解决这个问题。

同时已知 compatibility note：

```text
ConfigurationError currently lives in app.core.config.

Legacy import path remains usable,
but ConfigurationError is no longer a subclass of LLMClientError.

No current repository caller depends on that inheritance relationship.
```

本任务不要借机重构整个 exception hierarchy。

---

# 4. TASK-014 Objective

为 LLM Provider HTTP 请求建立：

```text
explicit
configurable
bounded
testable
```

的 timeout contract。

核心目标：

> LLM Provider 调用不能依赖隐式 timeout 或形成无明确等待边界的请求行为。

本任务是后续：

```text
failure classification
retry policy
bounded retry
backoff
```

的 Reliability Foundation。

---

# 5. Required Scope

## 5.1 Explicit LLM Timeout Configuration

在现有 Settings/configuration 体系中增加明确的 LLM timeout 配置。

例如可能类似：

```text
LLM_TIMEOUT_SECONDS
```

但最终命名必须结合 repository 当前配置风格决定。

要求：

* 有合理默认值
* 支持 environment configuration
* 有必要的 validation
* `.env.example` 如适用则同步更新
* 不引入新的配置框架

优先保持配置简单。

除非 repository 当前架构明确需要，否则不要一次拆成：

```text
connect timeout
read timeout
write timeout
pool timeout
```

四套用户配置。

本 Task 的重点是建立清晰的整体 timeout contract，而不是设计复杂 timeout DSL。

---

## 5.2 Explicit httpx Timeout

现有 `LLMClient` 的 HTTP 请求必须使用显式 timeout。

不得继续完全依赖 httpx 的隐式行为。

实现应符合当前 `httpx.Client` ownership / lifecycle 设计。

特别注意：

如果 `LLMClient` 支持 injected `http_client`：

不要破坏现有 dependency injection 和测试能力。

不要因为 timeout 配置而无理由改变 HTTP client ownership contract。

---

## 5.3 Timeout Error Mapping

HTTP timeout 不应无条件将底层：

```python
httpx.TimeoutException
```

直接泄漏到上层业务。

请阅读当前 LLM error hierarchy 后设计一个最小且一致的项目级错误表示。

例如可能是：

```text
LLMTimeoutError
```

但具体名称和 inheritance 必须依据现有 repository 结构决定。

要求：

```text
httpx timeout
→ LLM infrastructure error
→ existing AgentRuntime / TaskExecutionService failure path
```

不得借本任务全面重构现有 error hierarchy。

---

## 5.4 Preserve Existing Failure Semantics

Timeout 最终失败时，应继续沿现有调用链传播：

```text
LLMClient
→ AgentRuntime
→ TaskExecutionService
→ Task FAILED
```

必须保持 TASK-009 的：

```text
Primary failure / Secondary persistence failure
```

语义。

不得让数据库 FAILED persistence error 覆盖真正的 timeout / Agent execution error。

---

## 5.5 Tests

增加 focused automated tests。

至少验证以下行为：

### A. Timeout configuration

验证显式 timeout configuration 能进入 LLM HTTP client/request behavior。

不要使用真实长时间等待测试。

---

### B. Timeout mapping

模拟：

```python
httpx.TimeoutException
```

或其适当子类。

验证：

```text
httpx timeout
→ expected project-level LLM error
```

并验证错误链 / message 如当前项目规范有要求。

---

### C. Regression

确保已有正常：

```text
LLM response
Tool calling
AgentRuntime
Task execution
Task query/list/filter
```

行为不被破坏。

如果现有测试已经足以覆盖 Task FAILED lifecycle，则不要为了本任务重复制造大量测试。

---

# 6. Explicit Non-Goals

本 TASK 不实现：

```text
automatic retry
retry count
exponential backoff
jitter
Retry-After support
429 retry policy
503 retry policy
circuit breaker
Tenacity
Celery
Redis Queue
Kafka
Message Queue
AgentRuntime retry
Tool retry
Task retry endpoint
background execution
distributed execution
```

也不要新增：

```text
LangChain
LangGraph
MCP
Multi-Agent
```

Retry / failure classification 应作为后续独立任务处理。

不要因为“Reliability Foundation”这个名字而一次实现整套 Reliability Framework。

---

# 7. Architecture Constraints

继续遵守：

```text
V1 no LangChain
V1 no LangGraph
no premature MCP
no premature Multi-Agent
no unnecessary abstraction
```

Repository 是 Source of Truth。

如果本 TASK 形成新的长期架构决策：

同步：

```text
docs/DECISIONS.md
```

但只有真正的 Architecture Decision 才记录。

不要把普通实现细节全部写入 DECISIONS。

Technical Debt 与 Future Feature 必须区分。

---

# 8. Scope Discipline

本 Task 的理想结果是：

```text
LLM request
    ↓
explicit timeout boundary
    ↓
success

or

timeout
    ↓
project-level LLM error
    ↓
existing Agent failure path
    ↓
Task FAILED
```

做到这里即可。

不要继续实现 retry。

---

# 9. Validation

完成实现后：

运行 repository 当前规定的 relevant tests。

如果标准工作目录为：

```text
backend/
```

则从该目录执行测试。

至少运行：

```text
focused TASK-014 tests
```

并尽可能运行：

```text
full pytest suite
```

如果 PostgreSQL integration tests 因环境缺少 `DATABASE_URL` 被 skip：

如实报告，不要伪造执行结果。

已知：

```text
StarletteDeprecationWarning
```

对应已有 `TD-001`，如果仍存在只需报告，不需要在 TASK-014 中修复。

---

# 10. Completion Report

完成后使用中文提供：

## Planned Write Set

实际计划写入的 repository-relative files。

## Files Changed

实际修改文件。

## Implementation Summary

说明：

* timeout contract 如何设计
* timeout 从哪里配置
* httpx 如何应用 timeout
* timeout exception 如何映射
* 为什么没有实现 retry

## Architecture Impact

说明是否产生新的 architecture decision。

## Tests

列出：

* 执行命令
* passed
* skipped
* warning
* failed

不得隐藏 skipped 或 warning。

## Scope Check

明确确认：

```text
是否实现 retry：否
是否引入新框架：否
是否修改 Task API：否
是否修改 repository 外文件：否
```

## Risks / Notes

只报告真实风险。

Finding / 自检问题按照：

```text
BLOCKER
IMPORTANT
NOTE
```

分类。

不要增加新的风险等级。

## Recommended Review Focus

告诉 Independent Reviewer 最值得检查的 3～5 个点。

---

不要执行：

```text
git commit
git push
```

Git Human Gate 由用户完成。


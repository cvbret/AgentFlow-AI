你现在负责继续开发：

`AgentFlow-AI`

Repository root：

`E:\AIProjects\AgentFlow-AI`

本次任务：

`TASK-015 - LLM Failure Classification Foundation`

请使用中文回复：

* 工作计划
* Planned Write Set
* Completion Report
* 问题与风险说明

英文工程术语、代码、class/function 名称和路径可以保留英文。

不要执行 `git commit` 或 `git push`。

---

## 0. Workspace Boundary Guard

任何写操作前执行：

```powershell
Get-Location
git rev-parse --show-toplevel
```

必须确认：

```text
E:\AIProjects\AgentFlow-AI
```

如果 Git root 不正确：

立即停止，不允许写入。

随后检查：

```powershell
git status
```

如果存在与当前 TASK-015 无关且无法解释的未提交修改：

先报告，不要擅自覆盖。

写操作前必须提供：

`Planned Write Set`

优先使用 repository-relative path。

所有写入必须位于 repository root 内。

---

# 1. Context Loading

Repository 是 Source of Truth。

优先阅读：

```text
docs/PROJECT.md
docs/CURRENT_STATE.md
docs/AI_HANDOFF.md
AGENTS.md
docs/ROADMAP.md
docs/TECH_DEBT.md
```

然后重点读取当前实际：

```text
backend/app/llm/client.py
backend/app/llm/
backend/app/core/config.py
backend/tests/test_llm_client.py
```

以及现有：

```text
LLMProviderError
LLMClientError
ConfigurationError
InvalidLLMResponseError
```

等错误定义。

如需判断 failure propagation，再按需读取：

```text
AgentRuntime
TaskExecutionService
relevant tests
```

如果：

```text
tasks/TASK-015.md
```

不存在，则根据本 Prompt 创建聚焦的任务规格。

不要读取整个 repository 历史。

---

# 2. Current Reliability Baseline

TASK-014 已建立：

```text
explicit LLM timeout configuration
LLM_TIMEOUT_SECONDS = 30.0
per-request httpx.Timeout
TimeoutException → LLMProviderError
exception chaining
HTTP client ownership preservation
```

当前还没有：

```text
retry policy
retryable / non-retryable classification
backoff
jitter
Retry-After
```

本 TASK 只建立：

**Failure Classification**

不执行自动 retry。

---

# 3. Problem Statement

当前不同 Provider failures 可能最终都表现为较通用的：

```text
LLMProviderError
```

但不同失败具有不同恢复性质。

例如：

```text
Timeout
→ potentially transient

connection failure
→ potentially transient

429 Too Many Requests
→ potentially transient

5xx provider failure
→ potentially transient

400 Bad Request
→ normally permanent for the same request

401 Unauthorized
→ permanent until configuration changes

403 Forbidden
→ normally non-retryable
```

后续 bounded retry policy 必须依赖明确的 failure classification。

TASK-015 的目标是：

> 让 LLM infrastructure 能明确表达一次 Provider failure 是否属于 retryable/transient failure，而不是现在直接实现 retry。

---

# 4. Required Scope

## 4.1 Establish Minimal Failure Classification Contract

根据 repository 当前 error hierarchy，选择最小且一致的实现方式。

可以考虑但不限于：

```text
LLMRetryableError
LLMNonRetryableError
```

或者：

```text
failure category / retryable property
```

但不要机械采用示例名称。

必须首先检查现有错误体系。

目标是使上层可以可靠区分：

```text
retryable provider failure
vs
non-retryable provider failure
```

不要建立过大的异常 taxonomy。

---

## 4.2 Timeout Classification

TASK-014 已有：

```text
httpx.TimeoutException
```

本 TASK 应明确其 classification。

原则上：

```text
timeout
→ retryable / transient provider failure
```

但仍不得执行 retry。

确保 TASK-014 已建立的：

```text
exception chaining
```

继续保持。

---

## 4.3 Connection Failure Classification

检查现有 httpx exception handling。

对于适合视为 transient 的 connection-level failures，建立 retryable classification。

不要 catch：

```python
Exception
```

然后全部标记 retryable。

只处理当前明确理解的 provider/network failure。

---

## 4.4 HTTP Status Classification

检查 `LLMClient` 当前如何处理 non-2xx response。

建立第一版明确 contract。

至少重点考虑：

```text
429
5xx
400
401
403
```

合理目标：

```text
429
→ retryable

5xx
→ retryable

400
→ non-retryable

401
→ non-retryable

403
→ non-retryable
```

对于其他 4xx：

可以采用简单且可解释的默认策略，例如视为 non-retryable，除非 repository 当前 contract 有更合理行为。

不要在 TASK-015 构建复杂 HTTP retry matrix。

---

## 4.5 Preserve Error Boundary

HTTP/provider details 应继续主要收敛在：

```text
LLMClient
```

不要让：

```text
AgentRuntime
TaskExecutionService
API layer
```

开始直接判断：

```text
429
503
401
```

上层应该面对项目级 LLM failure abstraction。

---

## 4.6 Preserve Existing Agent/Task Semantics

本 TASK 不改变：

```text
Task lifecycle
PENDING
→ RUNNING
→ FAILED / SUCCEEDED
```

任何 classified error 当前仍然应该正常失败并向上传播。

即：

```text
retryable failure
≠
automatically retry
```

当前仍然：

```text
LLM failure
→ AgentRuntime failure
→ TaskExecutionService
→ Task FAILED
```

TASK-009 的 primary/secondary failure semantics 必须保持。

---

# 5. Tests

增加 focused automated tests。

至少覆盖：

### Retryable failures

验证例如：

```text
timeout
429
representative 5xx
```

被分类为 retryable。

---

### Non-retryable failures

验证例如：

```text
400
401
403
```

被分类为 non-retryable。

---

### Exception Chain

如果底层存在：

```text
httpx exception
```

确认 project-level error 仍保留适当 exception chaining。

---

### No Retry

必须验证或通过清晰测试结构证明：

> TASK-015 并不会让一次 `LLMClient.chat()` 自动发送多个 HTTP requests。

例如 provider 第一次返回 retryable failure 后：

调用仍立即失败。

不要实现 retry 只为了测试。

---

### Regression

现有：

```text
normal LLM response
tool calling
AgentRuntime
TaskExecutionService
```

行为不应回归。

如果已有 full suite 足够覆盖，不要重复制造大量低价值测试。

---

# 6. Explicit Non-Goals

本 TASK 不实现：

```text
automatic retry
retry loop
max_attempts
backoff
exponential backoff
jitter
Retry-After handling
sleep
circuit breaker
Tenacity
queue
Celery
Redis Queue
Kafka
AgentRuntime retry
Tool retry
Task retry API
observability framework
```

不要引入：

```text
LangChain
LangGraph
MCP
Multi-Agent
```

---

# 7. Anti-Overengineering

不要一次建立十几个错误 class。

如果：

```text
retryable
vs
non-retryable
```

两个类别已经能满足当前需求，就优先保持简单。

不要为了未来某个 Provider 的特殊行为提前构建：

```text
provider plugin system
retry strategy registry
HTTP status DSL
policy engine
```

未来需求出现后再扩展。

---

# 8. Architecture Decision

如果只是扩展现有 LLM error abstraction：

通常不需要新增重大 Architecture Decision。

只有确实形成长期、跨模块的重要架构约束时才更新：

```text
docs/DECISIONS.md
```

不要把普通 implementation detail 写成 ADR。

---

# 9. Validation

从 repository 规定的工作目录运行：

```text
focused TASK-015 tests
```

以及：

```text
full pytest suite
```

真实报告：

```text
passed
failed
skipped
warning
```

如果：

```text
DATABASE_URL
```

仍缺失导致 PostgreSQL integration tests skip：

正常记录。

不要伪造测试执行。

---

# 10. Completion Report

完成后输出：

## Planned Write Set

## Files Changed

## Classification Design

说明：

* classification 如何表达
* 为什么选择该设计
* 哪些 failure retryable
* 哪些 failure non-retryable

## Error Mapping

至少说明：

```text
Timeout
Connection failure
429
5xx
400
401
403
```

分别映射为什么。

## No-Retry Verification

必须明确：

```text
本 TASK 没有自动 retry。
```

## Architecture Impact

是否新增长期架构决策。

## Tests

报告：

```text
focused tests
full suite
passed
failed
skipped
warning
```

## Scope Check

明确：

```text
automatic retry：否
backoff：否
新 Reliability framework：否
AgentRuntime retry：否
Task API 修改：否
repository 外写入：否
commit：否
push：否
```

## Risks / Notes

只使用：

```text
BLOCKER
IMPORTANT
NOTE
```

不要增加其他等级。

## Recommended Review Focus

给出 Independent Reviewer 最值得检查的 3～5 个问题。

完成后停止，等待 Independent Review。


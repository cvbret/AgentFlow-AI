你现在负责继续开发：

`AgentFlow-AI`

Repository root：

`E:\AIProjects\AgentFlow-AI`

本次任务：

`TASK-016 - Bounded LLM Retry Policy`

请使用中文回复：

* 工作计划
* Planned Write Set
* Completion Report
* 问题说明
* 风险说明

代码、文件路径、class/function 名称和英文工程术语可保留英文。

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

检查：

```powershell
git status
git diff
```

如果存在无法解释的已有修改：

先报告，不要覆盖。

写操作前必须输出：

`Planned Write Set`

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

重点读取：

```text
backend/app/core/config.py
backend/app/llm/client.py
backend/tests/test_llm_client.py
```

以及：

```text
LLMProviderError
retryable classification
TASK-014 timeout implementation
TASK-015 failure classification implementation
```

如需判断生命周期影响，可按需读取：

```text
AgentRuntime
TaskExecutionService
relevant tests
```

如果 `tasks/TASK-016.md` 不存在：

创建聚焦的 Task specification。

不要无目的读取整个 repository。

---

# 2. Current Reliability Baseline

当前已经具备：

```text
TASK-014
Explicit configurable LLM timeout

TASK-015
Failure classification
LLMProviderError.retryable
```

当前 mapping：

```text
timeout/network
→ retryable=True

429/5xx
→ retryable=True

4xx/default
→ retryable=False
```

目前尚未执行 automatic retry。

TASK-016 的目标是：

> 基于现有 `retryable` contract，实现有明确上限的 LLM Provider request retry。

---

# 3. Core Semantics

本 TASK 使用：

```text
max_attempts
```

而不是模糊的 `max_retries`。

定义：

```text
max_attempts = total HTTP request attempts
```

例如：

```text
max_attempts=3

attempt 1 = initial request
attempt 2 = first retry
attempt 3 = second retry
```

因此：

```text
maximum retries = max_attempts - 1
```

`max_attempts=1` 表示：

```text
只执行一次请求
不进行 retry
```

---

# 4. Configuration

在现有 Settings 中增加类似：

```text
LLM_MAX_ATTEMPTS
```

具体命名遵循 repository 当前配置风格。

建议默认值：

```text
3
```

但请结合现有架构确认。

要求：

* integer；
* `>= 1`；
* environment configurable；
* `.env.example` 如适用同步；
* 不引入新配置框架。

不要增加：

```text
max_retries
retry_delay
backoff_factor
jitter
```

等额外配置。

---

# 5. Retry Location

优先保持 retry policy 位于：

```text
LLMClient / LLM provider invocation boundary
```

而不是 AgentRuntime。

目标：

```text
AgentRuntime
    ↓
LLMClient.chat()
    ↓
bounded provider request attempts
```

不要让 AgentRuntime 开始读取：

```text
HTTP 429
503
Timeout
```

等底层 Provider detail。

Retry decision 必须依赖：

```python
LLMProviderError.retryable
```

而不是重新解析 HTTP status。

---

# 6. Required Behavior

## Retryable Failure

如果某次请求抛出：

```python
LLMProviderError(retryable=True)
```

并且仍有剩余 attempts：

允许再次请求。

---

## Non-Retryable Failure

如果：

```python
retryable=False
```

立即抛出。

不得进行第二次 HTTP request。

---

## Attempts Exhausted

如果所有允许 attempts 都发生 retryable failure：

最终失败。

必须保持真实 Provider failure。

不要创建没有必要的复杂：

```text
RetryExhaustedError hierarchy
```

除非 repository 当前 error model 明确需要。

优先继续抛出最后一次：

```text
LLMProviderError
```

并保留原有 exception chaining。

---

## Success After Retry

例如：

```text
attempt 1
→ retryable failure

attempt 2
→ success
```

`LLMClient.chat()` 应正常返回成功结果。

上层不应该知道第一次失败过。

---

# 7. Task Lifecycle

本 TASK 不修改：

```text
PENDING
→ RUNNING
→ SUCCEEDED / FAILED
```

Retry 是一次 execution 内部行为。

不能出现：

```text
RUNNING
→ FAILED
→ RUNNING
```

每一次 retry 不应持久化新的 Task status。

只有：

```text
所有 attempts 最终失败
```

时，上层现有 failure path 才使 Task 进入：

```text
FAILED
```

如果最终成功：

```text
Task
→ SUCCEEDED
```

---

# 8. 600+ Review Note

TASK-015 Reviewer 记录：

```text
status_code >= 500
```

会把非标准 `600+` 状态码归为 retryable。

本 TASK 在接入真正 retry policy 前，应评估是否值得最小修正为：

```python
500 <= status_code < 600
```

如果修改成本很低且不会扩大 scope，可以在 TASK-016 中收紧。

如果不修改：

Completion Report 中说明理由。

不要为该 NOTE 建复杂协议层。

---

# 9. Tests

增加 focused automated tests。

至少覆盖：

## A. Retryable eventually succeeds

例如：

```text
attempt 1
→ retryable failure

attempt 2
→ success
```

验证：

```text
request_count == 2
```

并返回正常结果。

---

## B. Retryable exhausts attempts

例如：

```text
max_attempts=3

1 → retryable failure
2 → retryable failure
3 → retryable failure
```

验证：

```text
request_count == 3
```

最终抛出最后的 project-level LLM failure。

---

## C. Non-retryable never retries

例如：

```text
401 / retryable=False
```

验证：

```text
request_count == 1
```

即使：

```text
max_attempts > 1
```

也不得 retry。

---

## D. max_attempts=1

retryable failure 时：

```text
request_count == 1
```

不得 retry。

---

## E. Success on first attempt

确认：

```text
request_count == 1
```

没有多余请求。

---

## F. Existing Classification

确保 retry policy 只消费：

```text
LLMProviderError.retryable
```

不要在 retry loop 中重新判断：

```text
429
5xx
TimeoutException
```

---

## G. Regression

确保现有：

```text
timeout
failure classification
normal LLM response
tool calling
AgentRuntime
TaskExecutionService
```

行为无回归。

---

# 10. Explicit Non-Goals

本 TASK 不实现：

```text
sleep
fixed delay
backoff
exponential backoff
jitter
Retry-After
rate-limit specific delay
circuit breaker
Tenacity
queue
Celery
Redis Queue
Kafka
AgentRuntime retry
Tool retry
Task retry endpoint
background worker
distributed execution
```

不引入：

```text
LangChain
LangGraph
MCP
Multi-Agent
```

---

# 11. Anti-Overengineering

优先使用明确、可测试的 Python control flow。

不要因为 retry 引入：

```text
RetryStrategyFactory
RetryPolicyRegistry
ProviderRetryPlugin
middleware framework
```

如果简单 bounded loop 足够：

就保持简单。

---

# 12. Architecture Constraints

Retry policy 应消费：

```text
LLMProviderError.retryable
```

而不是重复理解 Provider protocol。

保持：

```text
HTTP details
→ LLMClient classification
→ bounded retry policy
```

Task lifecycle 和 AgentRuntime 不应承担 Provider retry semantics。

---

# 13. Validation

执行：

```powershell
.\venv\Scripts\python.exe -m pytest tests/test_llm_client.py -ra
```

以及：

```powershell
.\venv\Scripts\python.exe -m pytest -ra
```

报告真实：

```text
passed
failed
skipped
warning
```

如果无 `DATABASE_URL`：

PostgreSQL integration tests skip 正常报告。

---

# 14. Completion Report

完成后输出：

## Planned Write Set

## Files Changed

## Retry Policy Design

说明：

* `max_attempts` 定义
* 默认值
* retry loop 位于哪里
* 为什么不放 AgentRuntime

## Retry Decision

明确：

```text
retryable=True
→ may retry

retryable=False
→ fail immediately
```

## Attempts Semantics

明确例如：

```text
max_attempts=3
=
1 initial attempt + max 2 retries
```

## Exhaustion Semantics

说明所有 attempts 失败后：

最终抛出什么异常，以及是否保留最后真实 failure。

## Task Lifecycle Impact

明确：

```text
retry does not alter Task state per attempt
```

## 600+ NOTE Handling

说明是否收紧 `5xx` 判断。

## Tests

报告：

```text
focused
full suite
passed
failed
skipped
warning
```

## Scope Check

明确：

```text
bounded retry：是
backoff：否
sleep：否
Retry-After：否
AgentRuntime retry：否
Task API 修改：否
新 Reliability framework：否
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

## Recommended Review Focus

重点建议 Reviewer 检查：

1. max_attempts 是否存在 off-by-one；
2. non-retryable 是否绝不重复请求；
3. exhaustion 是否保留最终真实 failure；
4. retry 是否只依赖 `retryable`；
5. Task/Agent lifecycle 是否无回归。

完成后停止，等待 Independent Review。


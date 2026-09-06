# Technical Debt

The following maintenance items have been reviewed and intentionally accepted for the current phase.

中文释义：以下事项已经经过审查，并作为当前阶段可接受的维护事项记录下来。Technical Debt 不代表项目不能存在妥协；真正危险的是不知道妥协在哪里、为什么存在、风险是什么，以及未来如何偿还。

When a compromise is intentionally accepted, record it with the following fields:

* **ID**
* **Current Situation**
* **Reason Accepted**
* **Risk**
* **Resolution Plan**
* **Priority**

中文释义：每条技术债都应能被定位、解释和安排后续处理。没有这些信息的“以后再说”不是可管理的技术债记录，而是隐藏风险。

## TD-001 - TestClient dependency deprecation warning

### Current Situation / 当前情况

FastAPI / Starlette `TestClient` currently produces the following third-party dependency warning:

`StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.`

中文释义：TASK-001 的测试可以正常执行，但当前 FastAPI / Starlette 测试客户端与 HTTP client 依赖组合会产生弃用警告。这是依赖兼容性提示，不是健康接口的业务错误。

### Reason Accepted / 接受原因

TASK-001 functionality and tests are working correctly. The warning comes from third-party dependency compatibility and is not caused by the current business implementation.

中文释义：当前功能和测试结果符合要求，因此暂不为一个不影响行为的第三方警告升级依赖或扩大任务范围。

### Risk / 风险

Future dependency upgrades may affect test-client compatibility.

中文释义：未来升级 FastAPI、Starlette 或 HTTP client 时，测试客户端的兼容性可能发生变化，导致测试启动或请求行为受到影响。

### Resolution Plan / 解决计划

Evaluate FastAPI / Starlette / HTTP client version compatibility together during a future dependency-maintenance phase.

中文释义：在后续统一维护依赖版本时整体评估兼容关系，不在本次状态同步中升级依赖。

### Priority / 优先级

Low

## TD-004 - Calculator accepts non-finite and boolean numeric inputs

### Current Situation / 当前情况

当前 Calculator input 使用普通 `float` validation。

因此可能接受：

* boolean
* NaN
* Infinity

### Reason Accepted / 接受原因

TASK-003 主要目标是验证 Tool abstraction、Registry 和安全的固定运算能力。

当前问题不会导致 arbitrary code execution，也不影响 Tool architecture。

### Risk / 风险

未来 Tool Calling 中可能生成语义异常 numeric result，例如：

* `nan`
* `inf`
* `-0.0`

并向后续 Agent reasoning 传播。

### Resolution Plan / 解决计划

后续维护阶段：

* 使用 strict numeric validation
* 拒绝 bool
* 拒绝 NaN
* 拒绝 positive / negative Infinity
* 增加边界测试

### Priority / 优先级

Low

## TD-003 - LLM HTTP timeout is not explicitly configured

**Status:** `Closed`

**Resolved by:** `TASK-014 - Reliability Foundation / LLM Request Timeout Foundation`

### Current Situation / 当前情况

TASK-002 时 `LLMClient` 使用 HTTPX 默认 timeout，未形成明确的 AgentFlow-AI 运行契约。

该问题已由 TASK-014 解决：当前已有显式 `LLM_TIMEOUT_SECONDS` 配置，默认值为 `30.0`，并在每次 HTTP request 中应用 `httpx.Timeout`。

### Reason Accepted / 接受原因

TASK-002 目标是建立最小 LLM Client abstraction，因此当时接受该配置缺口。

该接受原因仅保留作为历史上下文；TASK-014 已完成 timeout foundation。

### Risk / 风险

TASK-014 已消除隐式 timeout 风险。Retry policy、retryable vs non-retryable classification 和 backoff 仍属于后续 Reliability capability，不再作为 TD-003 的未完成项。

### Resolution Plan / 解决计划

已由 TASK-014 完成：显式 timeout configuration、默认值、输入 validation、per-request timeout application、timeout error mapping 及 automated tests。

后续 retry / backoff / failure classification 应作为独立 Reliability capability 设计，不属于 TD-003。

### Priority / 优先级

Low

## TD-002 - Backend working-directory dependency

### Current Situation / 当前情况

The standard test and Uvicorn commands currently depend on being run from the `backend/` directory. Running pytest directly from the repository root can fail because Python's import path does not include `backend`, resulting in:

`ModuleNotFoundError`

中文释义：当前 Python application root 是 `backend/`，所以从该目录启动测试和 Uvicorn 可以正常工作；从 repository root 直接运行时，`app` 包可能不在 Python import path 中。

### Reason Accepted / 接受原因

The project is at an early stage, and `backend/` is an independent Python application root. Running commands from `backend/` is currently a valid and explicit development workflow.

中文释义：当前项目规模较小，明确要求从 `backend/` 运行并不会阻碍 TASK-001。为了处理一个尚未影响当前开发流程的问题而提前改变项目配置，会扩大本次任务范围。

### Risk / 风险

Future CI, local development, or IDE workflows that run from the repository root may experience environment differences.

中文释义：未来如果 CI、本地脚本或 IDE 默认从仓库根目录执行测试，可能遇到导入路径差异，造成“本地能跑、自动化环境不能跑”的问题。

### Resolution Plan / 解决计划

During a future testing and engineering-configuration phase, choose one explicit solution, such as:

* documenting the standard working directory in `README.md`
* adding pytest / Python project configuration
* establishing a unified project-level command

中文释义：后续应选择一种统一方案，并把命令入口固定下来。本次不为此进行架构改动。

### Priority / 优先级

Low

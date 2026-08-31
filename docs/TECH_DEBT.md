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

## TD-003 - LLM HTTP timeout is not explicitly configured

### Current Situation / 当前情况

`LLMClient` 当前使用 HTTPX 默认 timeout。

Reviewer 验证当前默认值有限，不会无限等待，但该行为不是 AgentFlow-AI 明确配置的运行契约。

### Reason Accepted / 接受原因

TASK-002 目标是建立最小 LLM Client abstraction。

统一 timeout、retry 和 failure policy 属于后续 Reliability 阶段。

### Risk / 风险

未来 dependency 默认值变化、不同 Tool / Provider 对 timeout 要求不同、timeout 错误分类不统一，可能造成运行行为不明确。

### Resolution Plan / 解决计划

在 Reliability 阶段：

* 显式定义 LLM timeout 配置
* 建立 timeout error classification
* 增加对应测试
* 与 retry policy 一起设计

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

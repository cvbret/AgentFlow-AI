# TASK-003 - Tool Abstraction and Tool Registry

## Goal / 目标

建立第一版 Tool abstraction 和 Tool Registry，为未来 Tool Calling 和 Agent Runtime 提供统一的工具管理边界。

当前只实现：

```text
Future Agent Runtime
        ↓
    Tool Registry
        ↓
      Tool
```

不实现 `LLM → tool_call → execution` 闭环。

## Scope / 范围

* `backend/app/tools/`
* `backend/tests/`

## Requirements / 要求

1. Tool 至少定义 `name`、`description`、`input schema` 和 execution implementation。
2. Tool input 必须通过关联的 Pydantic schema 验证。
3. 提供最小 `ToolResult`，只暴露可预测的 text content。
4. `ToolRegistry` 支持 `register`、`get` 和 metadata `list`。
5. 禁止重复 Tool name，并抛出清晰的 `DuplicateToolError`。
6. 查询不存在的 Tool 必须抛出 `ToolNotFoundError`。
7. Tool name 至少非空且不包含明显非法空白。
8. 增加安全的 `CalculatorTool`，只支持 add、subtract、multiply、divide。

## Tests / 测试

必须覆盖：

* Calculator 四种基础运算
* 非法 operation
* divide by zero
* Tool 注册与名称获取
* 重复注册
* Tool 不存在
* Registry metadata
* Pydantic input validation

测试不得使用真实外部服务。

## Architecture Constraints / 架构约束

不得实现：

* LLM tool_calls
* Agent Runtime 或 Agent Loop
* Tool Dispatcher orchestration
* Provider-specific Tool schema
* LangChain、LangGraph、MCP
* database、Redis、PostgreSQL
* retries、permissions、side-effect approval
* dynamic plugin loading

不要使用 `eval()`，不要为未来的多个 Provider 或几十种 Tool 提前创建复杂 Factory、Adapter 或 Plugin System。

## Acceptance Criteria / 验收标准

* Tool contract、input schema、ToolResult 和 Registry 边界清晰。
* CalculatorTool 可测试且不执行任意 Python expression。
* TASK-001、TASK-002 和 TASK-003 测试全部通过。
* 从 `backend/` 执行 `.\venv\Scripts\python.exe -m pytest` 成功。

## Task Status / 任务状态

Developer implementation is not complete until Independent Review and Project State Synchronization have passed.

# TASK-004 - Tool Calling Integration

## Goal / 目标

建立第一版 provider-compatible Tool Calling integration，使 LLM 能返回结构化 `ToolCall`，系统能够验证并执行对应的已注册 Tool。

当前只打通一次调用：

```text
Messages
   ↓
LLM Client
   ↓
Tool Call Parsing
   ↓
Tool Registry Lookup
   ↓
Tool Input Validation
   ↓
Tool Execution
   ↓
ToolExecutionResult
```

不实现完整 Agent Loop，也不把执行结果再次发送给 LLM。

## Scope / 范围

* `backend/app/llm/`
* `backend/app/tools/`
* `backend/tests/`

## Requirements / 要求

1. 扩展 message schema，支持 `tool` message 所需的最小字段。
2. 提供 provider-neutral `ToolCall` model：`id`、`name`、`arguments`。
3. 扩展 `LLMResponse`，同时表达普通 `content` 和 `tool_calls`。
4. 将 Tool metadata 转换为 OpenAI-compatible tool schema，但不污染 Tool domain model。
5. 扩展 `LLMClient.chat(messages, tools=None)`，无 tools 时保持 TASK-002 行为。
6. 解析 provider 返回的 tool call，并将 JSON string arguments 转换为 dict。
7. 提供单次 `ToolExecutor`，通过 Registry 查找并执行 Tool。
8. 提供 `ToolExecutionResult`，保存 `tool_call_id`、`tool_name` 和 content。

## Error Handling / 错误处理

清晰处理：

* unknown tool：沿用 `ToolNotFoundError`
* invalid arguments JSON：抛出 LLM response parsing error
* valid JSON but invalid Tool input：沿用 `ToolInputValidationError`
* Tool execution failure：沿用 `ToolExecutionError`

Integration Layer 不得吞掉已有 Tool domain error。

## Architecture Constraints / 架构约束

不得实现：

* Agent Runtime
* Agent Loop
* iterative LLM → Tool → LLM execution
* persistence、Task State 或 workflow state
* retries、timeout policy、permissions 或 approval
* provider-specific schema 写入 Tool domain
* LangChain、LangGraph、MCP 或 Multi-Agent
* dynamic function execution、shell 或 filesystem side effects

合法执行路径只能是：

```text
LLM ToolCall
↓
ToolRegistry.get(name)
↓
registered Tool
```

## Tests / 测试

所有 provider 请求必须 mock。至少覆盖普通 assistant response、tools request schema、ToolCall parsing、Calculator end-to-end、unknown tool、invalid arguments JSON、invalid Tool input、Tool execution failure，以及全部历史测试。

## Acceptance Criteria / 验收标准

* TASK-001、TASK-002、TASK-003 和 TASK-004 测试全部通过。
* Provider raw tool call JSON 不泄漏到上层 domain。
* Calculator Tool Call 能完成一次 `12 × 8 = 96` 执行。
* 从 `backend/` 执行 `.\venv\Scripts\python.exe -m pytest` 成功。

## Task Status / 任务状态

Developer implementation is not complete until Independent Review and Project State Synchronization have passed.

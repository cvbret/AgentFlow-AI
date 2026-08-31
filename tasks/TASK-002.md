# TASK-002 - First LLM Client Abstraction

## Goal / 目标

建立第一版 LLM Client abstraction，使未来 Application 或 Agent Runtime 不需要直接依赖具体模型供应商的 HTTP API。

未来上层应依赖类似 `llm_client.chat(messages)` 的稳定入口，而不是直接调用 `httpx.post(...)` 或散落 provider-specific client。

## Scope / 范围

* `backend/app/core/config.py`
* `backend/app/llm/`
* `backend/tests/`
* `.env.example`

当前只实现配置、消息/响应 schema 和 OpenAI-compatible Chat Completions client。

## Requirements / 要求

1. 使用已有的 `pydantic-settings` 加载 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`。
2. 提供结构化的 `ChatMessage`，支持 `system`、`user`、`assistant` 三种 role。
3. 提供最小 `LLMClient`，支持 `chat(messages)`。
4. 使用已有的 `httpx` 调用 `POST {LLM_BASE_URL}/chat/completions`。
5. 请求包含 `model`、`messages` 以及 `Bearer` Authorization header。
6. 返回最小的结构化 LLM response，并暴露 assistant text content。
7. 清晰处理配置错误、HTTP 错误和非法 provider response。
8. `.env.example` 只能包含占位值，不得包含真实 API Key。

## Tests / 测试

不得真实调用外部 LLM API。必须 mock HTTP request，并至少覆盖：

* 正常请求、请求 URL、Authorization、model、messages 和 assistant content
* provider 非 2xx 响应
* provider 非法 response structure
* 非法 message role

## Architecture Constraints / 架构约束

不得实现：

* Agent Runtime
* Agent Loop
* Tool Calling
* Tool Registry 或 Tool Dispatcher
* LangChain 或 LangGraph
* database、Redis 或 PostgreSQL
* retries、fallback provider、multi-provider router
* streaming 或 observability platform

不要为了未来可能出现的多个 Provider 提前创建复杂 Factory、Adapter 或 Plugin System。

## Acceptance Criteria / 验收标准

* LLM Client 与具体 provider HTTP 细节隔离。
* 配置和消息输入有清晰的类型边界。
* 相关测试通过，且 TASK-001 测试不被破坏。
* 从 `backend/` 执行 `.\venv\Scripts\python.exe -m pytest` 成功。

# TASK-011 - Expose Task ID from Agent Run

## Status

Not Started

## Goal

让 `POST /api/agent/run` 返回本次真实持久化 Task 的 `task_id` 和最终答案。

## Scope

- 将 Agent Run 成功响应扩展为 `task_id` 与 `answer`。
- `task_id` 来源于 `TaskExecutionService` 返回的 Domain Task。
- 通过 API 查询接口验证 POST → task_id → GET 闭环。
- 保持现有 Agent failure error mapping。

## Out of Scope

异步执行、queue、worker、Redis、retry、polling、cancellation、list API、
observability、LangGraph、Multi-Agent、TASK-012 和 state synchronization。

## Verification

从 backend/ 设置 DATABASE_URL 并执行 migration 后运行：

    .\venv\Scripts\python.exe -m pytest -ra

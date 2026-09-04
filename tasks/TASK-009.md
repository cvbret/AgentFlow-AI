# TASK-009 - Task Execution Integration

## Status

Not Started

## Goal

将 Task Domain、TaskRepository 和 AgentRuntime 串联为可持久化的任务执行生命周期。

## Scope

- 增加最小 `TaskExecutionService`。
- 通过 Session dependency 注入 TaskRepository。
- 让 `POST /api/agent/run` 经过 TaskExecutionService 执行。
- 持久化 PENDING、RUNNING、SUCCEEDED 和 FAILED 生命周期状态。
- 使用 fake runtime 与真实 PostgreSQL 验证 API 和数据库联动。

## Out of Scope

Redis、queue、worker、retry、polling、cancellation、observability、Task query API、
LangGraph、Multi-Agent、TASK-010 和 project state synchronization。

## Verification

从 backend/ 设置 DATABASE_URL 后执行：

    python -m alembic upgrade head
    .\venv\Scripts\python.exe -m pytest -ra

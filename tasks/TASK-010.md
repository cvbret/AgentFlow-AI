# TASK-010 - Task Query API

## Status

Not Started

## Goal

提供最小单 Task 查询接口 `GET /api/tasks/{task_id}`。

## Scope

- 使用 UUID path parameter 查询持久化 Task。
- 通过 `TaskRepository` 获取 Domain Task。
- 使用独立 Response DTO 返回安全、稳定的 Task 数据。
- 缺失 Task 返回 404，非法 UUID 返回 422。
- 使用 request-scoped SQLAlchemy Session，并保留真实 PostgreSQL integration test。

## Out of Scope

Task list、pagination、filter、search、sorting、Task query extensions、
Agent Run contract changes、Redis、queue、worker、retry、TASK-011 和 state synchronization。

## Verification

从 backend/ 设置 DATABASE_URL 并执行 migration 后运行：

    .\venv\Scripts\python.exe -m pytest -ra

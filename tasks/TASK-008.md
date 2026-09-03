# TASK-008 - PostgreSQL Task Persistence

## Status

Not Started

## Goal

为 Task State Domain 建立 Domain 与 SQLAlchemy ORM 分离的 PostgreSQL durable persistence。

## Scope

- 增加 SQLAlchemy Base、Session 和 TaskRecord。
- 使用 Alembic 创建 tasks 表。
- 提供最小 TaskRepository.save/get。
- 增加受控 Task.restore() 以验证数据库 rehydration。
- 使用 timezone-aware PostgreSQL timestamps。
- 通过独立 PostgreSQL integration tests 验证持久化。

## Out of Scope

No Agent API integration, Redis, queue, task worker, execution history,
observability, or TASK-009 functionality.

## Verification

从 backend/ 设置 DATABASE_URL 后执行：

    python -m alembic upgrade head
    .\venv\Scripts\python.exe -m pytest -ra

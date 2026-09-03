# TASK-007 - Task State Foundation

## Status

Not Started

## Goal

建立 provider-independent、storage-independent 的 Task State Domain。

## Scope

- 使用 UUID 作为 Task identity。
- 定义 PENDING、RUNNING、SUCCEEDED、FAILED。
- 提供 UTC timezone-aware timestamps。
- 通过 start、succeed、fail 管理生命周期。
- 保持 result/error domain invariants。
- 增加 domain contract tests。

## Out of Scope

No FastAPI Task API, AgentRuntime integration, PostgreSQL, SQLAlchemy,
Alembic, Redis, queues, persistence, execution history, or observability.

## Verification

Run from backend/:

    .\venv\Scripts\python.exe -m pytest

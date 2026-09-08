# TASK-026 - LangGraph Durable Workflow Foundation

## Objective

Prove PostgreSQL interrupt/resume after the original graph, saver, connection and Python process exit. Adopt LangGraph incrementally without migrating AgentRuntime.

## Scope / Requirements

- Sync StateGraph: START -> durable_pause -> END; interrupt precedes any side effect.
- AgentGraphState contains task_id and optional resume_result strings.
- task_id_to_thread_id maps AgentFlow Task.id to configurable.thread_id, distinct from internal LangGraph task IDs.
- open_checkpointer owns a sync PostgresSaver connection; setup is never implicit.
- Explicit setup from backend: python -m app.workflows.setup, using DATABASE_URL only.
- Official setup owns checkpoint schema; Alembic owns business tables.

## Non-goals

No AgentRuntime/API migration, LLM/Tool nodes, Approval integration, Task resume, approved execution, ledger, idempotency, reconciliation, queues or workers.

## Acceptance / Test Plan

Unit: mapping, state, interrupt/resume payload, explicit setup and URL adaptation.
PostgreSQL: process A pauses two threads and exits; process B constructs a fresh graph/saver and resumes with Command only. A third connection verifies final durable state and isolation.
Run focused and full suites. Independent Review precedes project completion synchronization.

## Dependencies

LangGraph 1.2.11; langgraph-checkpoint-postgres 3.1.2; existing psycopg 3.2.12. New transitive dependencies are pinned. Requirements encoding is UTF-8. No AgentExecutor migration.

Business/checkpoint commit consistency belongs to future integration; this graph performs no business writes.

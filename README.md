# AgentFlow-AI

AgentFlow-AI is an enterprise-oriented AI agent backend for controlled multi-step task execution.

中文释义：项目目标是让 Agent 围绕任务进行推理、工具调用、状态更新和结果交付，而不是只提供普通聊天能力。

## Current Status / 当前状态

Phase 1 - Core Agent Runtime. The project is in active development.

当前已建立 FastAPI Agent、PostgreSQL Task/Approval/Execution Ledger、LangGraph durable HITL/resume/recovery 和 structured observability。已确认状态见 `docs/CURRENT_STATE.md`；TASK-032 release qualification 记录见 `tasks/TASK-032.md`，开发验证不代表独立审查完成。

## Core Goal / 核心目标

Build a reliable, testable backend with an explicit execution flow:

`Task → Reasoning → Tool Calling → Tool Result → State Update → Final Result`

## Current Technology Stack / 当前技术栈

* Python
* FastAPI
* Uvicorn
* Pydantic
* PostgreSQL, SQLAlchemy and Alembic
* LangGraph with PostgreSQL checkpoints
* pytest and HTTPX for testing

This list reflects the current repository baseline; future technologies require an explicit need and architectural decision.

## Project Documentation / 项目文档

* [`docs/PROJECT.md`](docs/PROJECT.md) — project goals, scope, principles, and source of truth
* [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — current logical architecture and dependency direction
* [`docs/ROADMAP.md`](docs/ROADMAP.md) — staged development roadmap
* [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) — repository-confirmed current status
* [`docs/DECISIONS.md`](docs/DECISIONS.md) — architecture decision records
* [`docs/TECH_DEBT.md`](docs/TECH_DEBT.md) — intentionally accepted technical debt
* [`AGENTS.md`](AGENTS.md) — long-term AI Coding Agent rules
* [`tasks/TASK-001.md`](tasks/TASK-001.md) — first implementation task definition


## Clean Local Start / 干净环境启动

Validated qualification environment: Windows, Python 3.11 and PostgreSQL 17.
Use a dedicated PostgreSQL database. The repository currently has no Dockerfile,
compose application stack or CI workflow; provisioning PostgreSQL and deployment
are external prerequisites, not automatic application startup steps.

From the repository root (PowerShell):

```powershell
New-Item -ItemType Directory -Force .venv/tmp | Out-Null
$env:TEMP = (Resolve-Path .venv/tmp).Path
$env:TMP = $env:TEMP
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-cache-dir -r backend/requirements.txt
.\.venv\Scripts\python.exe -m pip check
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` locally: set DATABASE_URL to the prepared database and supply the
provider's LLM_API_KEY, LLM_BASE_URL and LLM_MODEL. Do not overwrite an existing
configured `.env`. All current Settings fields and constraints are documented in
`.env.example`; process environment variables override file values.

Initialize both independent schemas, then start the backend:

```powershell
Set-Location backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m app.workflows.setup
..\.venv\Scripts\python.exe -m alembic check
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Alembic owns the business tables; PostgresSaver owns its checkpoint tables.
Application startup does not automatically migrate either schema. Alembic currently
loads the shared Settings, so its configuration also requires the LLM fields
(existing TD-005); harmless placeholders suffice for migrations/tests that do not
call a real provider. Never run downgrade against a database whose business data
must be retained.

In another PowerShell session:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/tasks
```

`POST /api/agent/run` accepts `{"message":"..."}` and uses the configured provider.
The default registry contains Calculator; protected Tool qualification uses a
controlled test Tool, not a newly installed external integration. API definitions
are available at `/docs`. PostgreSQL-backed tests must use a separate disposable
database: integration fixtures clean business rows.

From `backend`, after initializing that test database:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_release_e2e.py tests/test_migration_qualification.py -q
..\.venv\Scripts\python.exe -m pytest -q
```

A test run without DATABASE_URL can skip PostgreSQL integration tests and is not
release qualification. TASK-032 uses a real database, a controlled provider, fresh
app/Runtime/Saver continuation and a real Uvicorn process, with zero acceptance skips.

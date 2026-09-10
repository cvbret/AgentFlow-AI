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
Use a dedicated PostgreSQL database. The Python-only path below requires an
existing PostgreSQL server. A separate Compose path is documented below.

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


## Docker Development Start / 容器开发启动

Requires Docker Engine/Desktop with Linux containers and Docker Compose. From
repository root:

```powershell
docker build --no-cache -t agentflow-local .
docker compose -p agentflow-local up -d --build --wait
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/tasks
docker compose -p agentflow-local ps
```

The backend uses Python 3.11 and runs as UID 10001. PostgreSQL 17 is private to
the Compose network; only backend port 8000 is published, on 127.0.0.1. Set
BACKEND_PORT in the shell to change the host port. The image build context uses
an allowlist and never includes host venvs, .git, .env, test artifacts or logs.
Provider values are runtime environment configuration, never build arguments.

Compose reads LLM_* and RECOVERY_STALE_AFTER_SECONDS from shell variables or the
root .env. With no configuration it uses harmless provider placeholders: health,
task queries and request validation work, but a successful Agent answer requires
a working provider. Use .env.example as a reference; never commit real secrets.
Local qualification uses a controlled provider; it does not validate an external
provider account, availability or billing.

The Compose database credentials (`agentflow` / `agentflow_dev_only`) are public,
development-only defaults, not production secrets. Compose deliberately supplies
its own DATABASE_URL with host `postgres`; the root .env DATABASE_URL remains for
Python running on the host and is NOT used by the Compose backend. To change DB
credentials, update both services together in an untracked, locally managed
Compose override; URL-encode password characters in DATABASE_URL. Existing volume
credentials are not changed by editing POSTGRES_PASSWORD. Do not use this stack
as production deployment configuration.

Compose waits for PostgreSQL's health check. The explicit container entrypoint
then runs `alembic upgrade head`, followed by `python -m app.workflows.setup`,
then execs Uvicorn. This does not add schema side effects to FastAPI import or
lifespan. Alembic owns business tables; PostgresSaver owns checkpoint tables.
Both initialization commands are repeatable. A failed phase exits nonzero and
never starts Uvicorn. Startup failure logs identify the phase without exposing
raw configuration/driver exceptions. Diagnose the named command in a trusted
local environment; keep raw diagnostic output private.

The backend health check calls its own /api/health and only succeeds once the API
responds. It is an HTTP liveness check, not continuous DB/provider readiness or
proof of production availability. The standalone image also needs a reachable,
ready DATABASE_URL and required LLM settings; it fails closed if initialization
cannot connect (bounded by PGCONNECT_TIMEOUT, default 5 seconds).

```powershell
docker compose -p agentflow-local restart backend
docker compose -p agentflow-local up -d --wait
docker compose -p agentflow-local down
# DESTRUCTIVE for this project's development database: removes its stored data.
docker compose -p agentflow-local down -v
```

Ordinary down/restart preserves the named database volume. down -v is only for a
disposable clean-start verification. Do not apply it to data you need to keep.

## CI Qualification

.github/workflows/ci.yml runs on pushes and pull requests to main. It uses official
checkout@v7 and setup-python@v7, Python 3.11, and a healthy PostgreSQL 17 service.
It installs requirements, runs pip check, initializes both schemas, checks Alembic
drift, runs the full PostgreSQL suite and builds the Docker image without cache.
All provider credentials are fake. There is no registry push or deployment step.

From backend, with an initialized disposable test database and repo-local TEMP/TMP,
`python -m scripts.qualified_tests -q` runs the full suite and additionally fails
on any skipped test (including collection skips) or pytest warning. It does not
suppress warnings or weaken existing tests. The existing plain pytest commands
remain useful for focused development; their success alone is not qualification
if PostgreSQL tests were skipped.

CI implementation/local reproduction and a real hosted Actions run are separate
evidence. See tasks/TASK-033.md for actual validation results. GitHub-hosted CI
evidence pending Human Gate push. Deployment Qualification = Not Yet Qualified.

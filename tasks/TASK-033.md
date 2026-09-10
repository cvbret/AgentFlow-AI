# TASK-033 - Container & CI Delivery Qualification

Status: Developer implementation and local validation complete; independent review pending.

Scope: Python 3.11 application image, PostgreSQL 17 + backend Compose, explicit
Alembic then PostgresSaver initialization, health checks, restart qualification,
GitHub Actions full PostgreSQL test gate and image build. No Runtime expansion,
registry push, CD or production deployment qualification.

Planned Write Set: Dockerfile, .dockerignore, compose.yaml,
.gitattributes (added before writing to preserve shell LF on Windows),
backend/container-entrypoint.sh, backend/scripts/, relevant delivery tests,
.github/workflows/ci.yml, README.md, tasks/TASK-033.md,
docs/ARCHITECTURE.md and docs/DECISIONS.md. Ignored validation files: .venv/tmp/task033/.

Workspace: verified E:\AIProjects\AgentFlow-AI, clean main at 3dc7b85 before edits.
TEMP/TMP redirected before temporary operations. Docker client configuration uses
repo-local .venv/tmp/task033/docker with the existing daemon endpoint; no global
Docker configuration is changed. Docker-managed images/containers/volumes are the
explicitly requested delivery verification infrastructure.

CI workflow uses official checkout@v7 and setup-python@v7, verified from their
upstream README examples on 2026-09-10. GitHub-hosted CI evidence pending Human Gate push.
Deployment Qualification = Not Yet Qualified.


## Delivered architecture

Python 3.11-slim application image, explicit /app/backend working directory and
COPY inputs; runtime UID 10001; Uvicorn is PID 1 after shell exec. Root is used
only during image dependency installation and the ephemeral CI reproduction.
Compose has exactly PostgreSQL 17 and backend services. TCP pg_isready avoids
mistaking PostgreSQL's initialization-only Unix socket server for a ready DB.
Only the backend port is published, bound to host loopback. No Redis or new
Runtime functionality. Public Compose credentials are development-only.

The explicit entrypoint invokes Alembic upgrade head then the existing
app.workflows.setup CLI. It exits nonzero on either failure, prints only a safe
phase message and starts no API. FastAPI import/lifespan remains unchanged.
PostgresSaver DDL remains framework-owned, outside business migrations. An HTTP
healthcheck becomes healthy after Uvicorn responds; it is not a continuous DB or
provider readiness guarantee. .gitattributes fixes shell LF on Windows checkout.

## Validation evidence (2026-09-10)

Environment: Windows Docker Desktop Engine 29.5.2 / Compose 5.1.4, Linux Python
3.11.16 image and PostgreSQL 17. All commands ran from this repository. Dedicated
Compose project: agentflow-task033; explicit --env-file .env.example and shell
placeholder provider overrides avoid reading or using real local credentials.
The controlled HTTP provider was an ephemeral test container on this project's
network, not a third production Compose service or an external provider test.

### Build and clean start

- `docker build --no-cache --progress plain -t agentflow-task033:qualification .`:
  PASS. Successful image manifest list:
  sha256:e12fa774e9d63e820085f31ca693ee1c07b26dd50fb77af52abe590a317240a3.
- Initial two builds failed pip's download hash validation. No hashes, requirements,
  resolver security checks or TLS verification were bypassed. A standalone wheel
  diagnostic and subsequent unchanged dependency download succeeded. Root cause
  of the transient download mismatch is unconfirmed; it is not silently reported
  as first-attempt success. Final two no-cache builds passed.
- `docker compose --env-file .env.example -p agentflow-task033 down -v`, then
  `up -d --wait postgres`: a new named volume was created; SQL verified **0** public
  tables before backend initialization. Repeated with final TCP health configuration.
- `up -d --build --wait --wait-timeout 90`: PostgreSQL healthy, backend healthy.
- Actual SQL table set: alembic_version, tasks, approvals, tool_executions,
  checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations.
- Actual Alembic head: 0003_create_tool_executions; checkpoint migration versions:
  0,1,2,3,4,5,6,7,8,9.
- /api/health returned status ok; POST /api/agent/run returned succeeded and the
  controlled provider answer; GET /api/tasks/{id} and /api/tasks returned the
  persisted Task. Responses included server-generated X-Request-ID.
- `restart backend` then `up -d --wait`: healthy again; identical Task ID/status,
  table set, Alembic head and checkpoint migration versions. Both initialization
  phases ran successfully again. Final configuration repeated this proof.

### Failure, process and secret checks

- Unavailable database: actual entrypoint exited 1 before API startup.
- Invalid migration configuration: exited 1; fake secret input absent from logs.
- Injected exception in only the setup CLI using a read-only test mount: real
  Alembic completed, checkpoint phase failed, exit 1; no API startup or secret leak.
- Live container checked UID=10001 and /proc/1/cmdline containing Uvicorn.
- Image /app tree contained no .env, .git, venv, .venv or Python/test caches.
- Startup/API logs contained no sentinel API key, development DB password or raw
  DATABASE_URL. Entry point does not print captured driver/configuration errors.
- Compose configuration validation and workflow YAML/trigger/service/command
  structure validation passed. This was static validation, not a hosted Actions run.

### CI local command reproduction

Used a new disposable agentflow_ci database in the PostgreSQL service and an
isolated Linux application-image container. Tests and scripts were mounted read-only
from this repository; the image supplies app code and installed dependencies.
Reproduced in order:

```text
python -m pip install --no-cache-dir -r requirements.txt
python -m pip check
python -m alembic upgrade head
python -m app.workflows.setup
python -m alembic check
python -m scripts.qualified_tests -q -o cache_dir=/app/tmp/pytest_cache
# Back on the host, after successful full tests:
docker build --no-cache --progress plain -t agentflow-ci .
```

Every step passed. Image builds supplied the clean Linux dependency installation;
the test-container install revalidated the same review environment. Host .venv
requirements installation and pip check also passed with repo-local TEMP/TMP.
The local runner used the Compose network hostname postgres rather than CI's
host-mapped localhost; this is the expected network topology difference. Linux
container TEMP/TMP/TMPDIR and pytest cache stayed under /app/tmp. Host temporary
files stayed under .venv/tmp/task033. This reproduces critical commands, not the
GitHub runner/action infrastructure or an actual Ubuntu-hosted Actions job.

Final CI-equivalent image manifest list:
sha256:afac7dd06d765c6d58f61fed3bbed71298c61862414848f55bee7fc6e04de0a1.

Workflow: main push + pull_request, contents:read, Python 3.11, PostgreSQL 17
healthy service, harmless LLM/recovery configuration, explicit dual initialization,
full pytest qualification and no-cache Docker build. No secret/registry/CD steps.
Actions versions were checked against [checkout](https://github.com/actions/checkout)
and [setup-python](https://github.com/actions/setup-python) official examples.

**Container Delivery = Qualified (developer evidence; independent review pending).**
**CI Workflow = Implemented and locally validated.**
**GitHub-hosted CI evidence pending Human Gate push.**
CI Automation is not marked Qualified without a hosted run.
**Deployment Qualification = Not Yet Qualified.**

### Tests

| Suite | Passed | Failed | Skipped | Warnings |
| --- | ---: | ---: | ---: | ---: |
| Focused: delivery gate + release E2E + migration qualification | 23 | 0 | 0 | 0 |
| High-risk: release/migration/resume/ledger/recovery/observability | 138 | 0 | 0 | 0 |
| Full PostgreSQL Linux suite | 440 | 0 | 0 | 0 |

Focused: 8.40 s; high-risk: 17.80 s; full: 49.36 s. All original 432 tests retained;
8 new qualification gate tests added. Additional independent subprocess probes
intentionally produced one warning, one test skip and one collection skip: all
three were rejected with nonzero status. These are negative gate proofs, not
warnings/skips in the formal suite. Three startup fault checks also passed.

### Dependency and configuration audit

No requirements or application dependencies changed. pip check passed in host and
Linux image/reproduction. Existing 55 explicit requirement pins retained; existing
transitive Mako and MarkupSafe are still not directly pinned (observed 1.4.1 and
3.0.3); psycopg-binary is fixed by the existing psycopg extra (3.2.12). Floating base
image tags and existing unpinned transitives mean this is repeatable command
qualification, not a byte-for-byte locked supply chain. No new SDK/framework.

Only .env.example is tracked; .env and validation artifacts remain ignored. Real
.env contents were not read, copied or modified. The Docker allowlist excludes
root environments, Git data, temp directories and tests; explicit COPY inputs
prevent host packages entering the image. Compose DATABASE_URL uses postgres and
is deliberately independent from the host-only root .env DATABASE_URL.

## Findings and remaining decisions

- IMPORTANT (fixed during implementation): startup must not expose raw configuration
  errors; entrypoint reports the failed phase and exits without printing secrets.
- IMPORTANT (fixed during implementation): DB readiness uses TCP rather than the
  temporary initialization socket; final clean-start and restart proof passed.
- NOTE (fixed): shell LF is enforced for Windows checkout.
- NOTE: initial download hash mismatches were rejected; later unchanged downloads
  and two no-cache builds passed. The network/source cause was not established.
- NOTE: the first local probe encountered a Windows subprocess output decoding
  error; the repository-local probe was corrected to UTF-8 and final verification
  reran successfully. This did not affect application code or acceptance counts.
- Remaining release gaps: hosted CI evidence, real provider qualification and target
  deployment qualification. Current development DB defaults are not production
  secrets; multi-replica migration ownership is outside this task (ADR-010).
- No Producer decision blocks the current scope. Human Gate push is needed before
  hosted CI evidence can exist; production target decisions belong to a later task.

## Workspace and Git audit

Repository and working directory verified: E:\AIProjects\AgentFlow-AI.
Repository-relative writes used, with resolved containment checks on constructed
paths. Docker bind mount APIs require absolute host source paths; each resolved
source is inside this repository and mounted read-only. Docker client configuration,
Buildx state and host TEMP/TMP are repo-owned. No host venv bootstrap was necessary.
PI-002 did not repeat; no repository-external host file creation/modification/move/
deletion was observed. This is process evidence, not an OS-level forensic audit.
Docker-managed build/image/container/volume writes are the explicitly requested
container verification, not changes to other repositories or global Docker config.

Actual changes: README.md, docs/ARCHITECTURE.md, docs/DECISIONS.md; new Dockerfile,
.dockerignore, .gitattributes, compose.yaml, backend/container-entrypoint.sh,
backend/scripts/qualified_tests.py, backend/tests/test_delivery_gate.py,
.github/workflows/ci.yml and tasks/TASK-033.md. No application source, historical
migration, requirements, CURRENT_STATE or AI_HANDOFF changes. The handoff's earlier
"Pending commit" is stale: actual baseline was committed 3dc7b85 with clean main;
this task follows repository Git truth and does not rewrite the old state snapshot.

No git add, commit or push. Stop at Independent Review; no Completed project-state
synchronization is performed by Developer.

Final cleanup: the task033 controlled-provider container, Compose backend/PostgreSQL
containers, network and disposable volume were removed. Project-label container
and volume inventories are empty. Built images and ignored repo-local evidence
remain available for review. git diff --check passed; index remains empty.

# Real API HTTP E2E verification

Date: 2026-09-11. Developer verification; no project-wide production qualification claim.

## Root cause

The root .env and process environment lacked DATABASE_URL. Settings.database_url
was None and create_engine_from_settings raised ConfigurationError with the exact
internal reason DATABASE_URL is required. FastAPI resolves get_db_session before
TaskExecutionService and Runtime execution; the existing public error mapping
returned HTTP 500 / Agent configuration is unavailable. This was not a provider,
Calculator, LangGraph or root dotenv-loading failure.

## Changes and local configuration

Planned writes: local .env (database setting only), compose.host.yaml, README and
this verification note. Expanded before editing to two missing-configuration tests
in test_agent_api.py and test_llm_client.py. No production Runtime/API changes.
The user's existing config.py changes were preserved exactly.

Existing compose.yaml database identity and development credentials were reused.
Host ports 5432 and 5433 were occupied; loopback port 15432 was verified available
and exposed through compose.host.yaml. Started only the existing postgres service
under project agentflow-local. No unrelated containers were changed, no database
or volume was deleted/reset. The local .env gained a host DATABASE_URL; its API key
was checked unchanged immediately after append and was not printed.

The real server was started from backend with no manually injected LLM_* or
DATABASE_URL environment variables, using root .env automatically. Uvicorn reload
runs on 127.0.0.1:8001 because port 8000 was already occupied. Swagger:
http://127.0.0.1:8001/docs. PostgreSQL and this server remain available for local use.

## Database and HTTP evidence

Database SELECT 1 passed. Existing alembic upgrade head, app.workflows.setup and
alembic check passed against the new development database. Both business and
checkpoint initialization remain explicit; no destructive migration was performed.

POST /api/agent/run with the request to use calculator for 123 * 456 called the
configured real DeepSeek provider and returned HTTP 200, status succeeded, with
answer containing 123 * 456 = 56088.

Task ID: eb12c3b3-33e0-432d-bad0-46de07c3c9e3.
GET /api/tasks/{id} returned succeeded and the same result; GET /api/tasks included
that task. Uvicorn events contained two llm.request.started and two
llm.request.succeeded events. The final durable checkpoint contained calculator
ToolCall and a role=tool message with 56088, confirming actual Tool execution.
Safe Calculator execution does not emit the protected execution-ledger Tool events;
absence of those events was not interpreted as absence of a Tool call.

## Regression isolation finding

The first focused run returned 44 passed / 2 failed / 0 skipped / 0 warnings.
The two missing-config tests cleared environment variables but still read the
real .env; one unintentionally reached the real provider. Both tests now disable
dotenv through monkeypatch for that test only, preserving application behavior and
all assertions. Regression uses separate agentflow_test with fake LLM settings;
its cleanup fixtures never target the real HTTP Task database.

## Safety and remaining scope

No real secret was printed or committed. .env remains ignored/untracked. TEMP/TMP
and Docker client configuration for this task are repo-owned. No add/commit/push.
An automatic approval review rejected a combined secret-log comparison/document
command, and then a separate fenced-document write, returning blocked by policy
without further reason. The secret-log comparison was not retried or claimed as
completed. A simpler documentation write succeeded; this does not imply a complete
forensic log audit. No real key was changed; the API contract is unchanged.

This is real HTTP/Task/Calculator/provider integration proof, not production
availability, arbitrary Tool safety, external-key provider contract, or deployment
qualification. Existing project status is not overwritten by this local verification.

## Final regression results

From backend, using isolated agentflow_test and fake LLM process settings:

- python -m scripts.qualified_tests -q tests/test_agent_api.py tests/test_task_execution_integration.py tests/test_llm_client.py: 46 passed / 0 failed / 0 skipped / 0 warnings (1.68 s).
- python -m scripts.qualified_tests -q: 440 passed / 0 failed / 0 skipped / 0 warnings (35.59 s), including PostgreSQL integration.

Final Task query after full regression still returns succeeded. git diff --check passes. Final status: PASS WITH NOTES (alternate HTTP port, initial test-isolation failure corrected, secret-log comparison blocked as disclosed).

The original tool-managed Uvicorn session ended before final handoff. Restarted
as a hidden background reload server (PID 25988); final /docs and persisted Task
queries passed. Start-Process requires resolved executable/working/log paths; all
log targets were checked inside the repository before launch. No additional real
LLM call was needed for that final persistence check.

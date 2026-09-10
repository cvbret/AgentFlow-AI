#!/bin/sh
set -eu
# Compose waits for PostgreSQL health. Standalone unavailable DB fails closed.
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-5}"
# Do not expose raw configuration/driver exceptions (which can contain secrets).
if ! python -m alembic upgrade head >/dev/null 2>&1; then
    echo "Business schema initialization failed; backend not started." >&2
    exit 1
fi
echo "Business schema initialization complete."
if ! python -m app.workflows.setup >/dev/null 2>&1; then
    echo "Checkpoint schema initialization failed; backend not started." >&2
    exit 1
fi
echo "Checkpoint schema initialization complete."
exec "$@"

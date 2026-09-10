"""Real mixed-schema qualification; checkpoint DDL remains framework-owned."""
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import inspect, text

from test_approval_decision import engine


def alembic_check():
    return subprocess.run([sys.executable, "-m", "alembic", "check"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)


def test_alembic_check_accepts_business_and_checkpoint_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert {"tasks", "approvals", "tool_executions", "checkpoints", "checkpoint_blobs",
            "checkpoint_writes", "checkpoint_migrations"} <= tables
    result = alembic_check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "No new upgrade operations detected" in result.stdout


@pytest.mark.parametrize("kind", ["business_column", "unknown_table"])
def test_alembic_check_still_detects_real_drift(engine, kind):
    create = "ALTER TABLE tasks ADD COLUMN qualification_probe TEXT" if kind == "business_column" else "CREATE TABLE checkpoint_qualification_probe (id INTEGER)"
    drop = "ALTER TABLE tasks DROP COLUMN qualification_probe" if kind == "business_column" else "DROP TABLE checkpoint_qualification_probe"
    with engine.begin() as connection:
        connection.execute(text(create))
    try:
        result = alembic_check()
        assert result.returncode != 0
        assert "qualification_probe" in result.stdout + result.stderr
        assert ("remove_column" if kind == "business_column" else "remove_table") in result.stdout + result.stderr
    finally:
        with engine.begin() as connection:
            connection.execute(text(drop))

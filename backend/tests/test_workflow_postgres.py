import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest

from app.workflows.checkpoint import open_checkpointer, setup_checkpoints
from app.workflows.graph import task_id_to_thread_id


# A process boundary guarantees no Graph/checkpointer/Python state is shared.
WORKER = r"""
import json, os, sys
from uuid import UUID
from langgraph.types import Command
from app.workflows.checkpoint import open_checkpointer
from app.workflows.graph import build_foundation_graph, task_id_to_thread_id
phase, first, second = sys.argv[1:]
ids = [task_id_to_thread_id(UUID(first)), task_id_to_thread_id(UUID(second))]
configs = [{"configurable": {"thread_id": identity}} for identity in ids]
with open_checkpointer(os.environ["DATABASE_URL"]) as saver:
    connection = saver.conn
    graph = build_foundation_graph(saver)
    if phase == "pause":
        for identity, config in zip(ids, configs):
            result = graph.invoke({"task_id": identity}, config)
            assert result["__interrupt__"][0].value == {"task_id": identity, "kind": "durable_pause"}
            assert saver.get_tuple(config) is not None
    else:
        for identity, config in zip(ids, configs):
            snapshot = graph.get_state(config)
            assert snapshot.values == {"task_id": identity}
            assert snapshot.next == ("durable_pause",)
        # No initial state is submitted in this new process.
        first_result = graph.invoke(Command(resume="first-complete"), configs[0])
        assert first_result == {"task_id": ids[0], "resume_result": "first-complete"}
        assert graph.get_state(configs[0]).next == ()
        assert graph.get_state(configs[1]).next == ("durable_pause",)
        assert "resume_result" not in graph.get_state(configs[1]).values
        second_result = graph.invoke(Command(resume="second-complete"), configs[1])
        assert second_result == {"task_id": ids[1], "resume_result": "second-complete"}
        assert graph.get_state(configs[1]).next == ()
    del graph
assert connection.closed
del saver, connection
print(json.dumps({"phase": phase, "closed": True}))
"""


@pytest.fixture
def database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    return url


def test_explicit_postgres_setup_is_repeatable(database_url):
    setup_checkpoints(database_url)
    setup_checkpoints(database_url)
    with open_checkpointer(database_url) as saver:
        connection = saver.conn
        assert saver.get_tuple({"configurable": {"thread_id": str(uuid4())}}) is None
    assert connection.closed


def test_fresh_process_graph_and_checkpointer_resume_isolated_threads(database_url):
    setup_checkpoints(database_url)
    ids = [uuid4(), uuid4()]
    try:
        for phase in ("pause", "resume"):
            process = subprocess.run(
                [sys.executable, "-c", WORKER, phase, *map(str, ids)],
                capture_output=True, text=True, timeout=60,
            )
            assert process.returncode == 0, process.stderr
            assert json.loads(process.stdout) == {"phase": phase, "closed": True}
        # Third independent connection observes final persisted state.
        with open_checkpointer(database_url) as saver:
            from app.workflows.graph import build_foundation_graph
            graph = build_foundation_graph(saver)
            for task_id, expected in zip(ids, ("first-complete", "second-complete")):
                config = {"configurable": {"thread_id": task_id_to_thread_id(task_id)}}
                snapshot = graph.get_state(config)
                assert snapshot.values["resume_result"] == expected
                assert snapshot.next == ()
    finally:
        with open_checkpointer(database_url) as saver:
            for task_id in ids:
                saver.delete_thread(task_id_to_thread_id(task_id))

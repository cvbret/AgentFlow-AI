from unittest.mock import patch
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.tasks import Task
from app.workflows.graph import AgentGraphState, build_foundation_graph, task_id_to_thread_id
from app.workflows.checkpoint import postgres_connection_string, open_checkpointer, setup_checkpoints
from app.workflows.setup import main


def test_task_identity_mapping():
    task = Task(input="workflow identity")
    assert task_id_to_thread_id(task.id) == str(task.id)
    assert task_id_to_thread_id(task.id) == task_id_to_thread_id(task.id)
    assert task_id_to_thread_id(uuid4()) != task_id_to_thread_id(task.id)


def test_minimal_state_interrupt_and_resume():
    identity = task_id_to_thread_id(uuid4())
    state: AgentGraphState = {"task_id": identity}
    assert set(AgentGraphState.__annotations__) == {"task_id", "resume_result"}
    graph = build_foundation_graph(InMemorySaver())
    config = {"configurable": {"thread_id": identity}}
    paused = graph.invoke(state, config)
    assert paused["__interrupt__"][0].value == {"task_id": identity, "kind": "durable_pause"}
    assert graph.get_state(config).next == ("durable_pause",)
    result = graph.invoke(Command(resume="continued"), config)
    assert result == {"task_id": identity, "resume_result": "continued"}
    assert graph.get_state(config).next == ()


def test_resume_rejects_nonstring_payload():
    identity = task_id_to_thread_id(uuid4())
    graph = build_foundation_graph(InMemorySaver())
    config = {"configurable": {"thread_id": identity}}
    graph.invoke({"task_id": identity}, config)
    with pytest.raises(ValueError, match="string"):
        graph.invoke(Command(resume={"invalid": True}), config)


def test_database_url_adapter():
    assert postgres_connection_string("postgresql+psycopg://user:example@localhost/test?sslmode=require") == "postgresql://user:example@localhost/test?sslmode=require"
    with pytest.raises(ValueError, match="PostgreSQL"):
        postgres_connection_string("sqlite:///test.db")


def test_setup_is_explicit_and_not_runtime_default():
    with patch("app.workflows.checkpoint.PostgresSaver.from_conn_string") as factory:
        saver = factory.return_value.__enter__.return_value
        with open_checkpointer("postgresql://localhost/test"):
            pass
        saver.setup.assert_not_called()
        setup_checkpoints("postgresql://localhost/test")
        saver.setup.assert_called_once()
        assert factory.return_value.__exit__.call_count == 2


def test_setup_cli_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        main()

"""Communication domain validation and execution-boundary contracts."""
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.agents.communication import (
    AgentMessage, Artifact, ArtifactType, MessageType,
    CommunicationEvent, CommunicationEventName,
)


def message(**overrides):
    values = dict(task_id=uuid4(), sender_agent_id="planner",
                  receiver_agent_id="developer", message_type="REQUEST",
                  content="Implement the plan.")
    values.update(overrides)
    return AgentMessage(**values)


def artifact(**overrides):
    values = dict(artifact_type="PLAN", name="implementation-plan",
                  content={"steps": ["implement", "test"]})
    values.update(overrides)
    return Artifact(**values)


def test_message_defaults_and_unique_identity():
    first, second = message(), message()
    assert isinstance(first.message_id, UUID)
    assert first.message_id != second.message_id
    assert first.artifacts == ()
    assert first.metadata == {}
    assert first.created_at.utcoffset() == timedelta(0)
    assert first.message_type is MessageType.REQUEST


def test_message_serialization_preserves_identity_and_artifacts():
    original = message(artifacts=[artifact()], metadata={"iteration": 1})
    restored = AgentMessage.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.message_id == original.message_id
    assert restored.artifacts[0].artifact_id == original.artifacts[0].artifact_id


@pytest.mark.parametrize("kind", list(MessageType))
def test_all_message_types(kind):
    assert message(message_type=kind.value).message_type is kind


@pytest.mark.parametrize("kind", ["COMMAND", "EVENT", "QUERY", "NOTIFICATION", "request", ""])
def test_invalid_message_types(kind):
    with pytest.raises(ValidationError):
        message(message_type=kind)


@pytest.mark.parametrize("field,value", [
    ("task_id", "invalid"), ("message_id", "invalid"),
    ("sender_agent_id", ""), ("receiver_agent_id", " \n"),
    ("sender_agent_id", 123), ("content", ""), ("content", {"unexpected": True}),
    ("artifacts", [{}]), ("metadata", {"object": object()}),
    ("created_at", datetime(2026, 1, 1)),
])
def test_invalid_message_fields(field, value):
    with pytest.raises(ValidationError):
        message(**{field: value})


@pytest.mark.parametrize("field", [
    "task_id", "sender_agent_id", "receiver_agent_id", "message_type", "content",
])
def test_required_message_fields(field):
    values = message().model_dump()
    del values[field]
    with pytest.raises(ValidationError):
        AgentMessage(**values)


def test_utc_normalization():
    supplied = datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))
    assert message(created_at=supplied).created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_metadata_and_artifact_inputs_are_snapshots():
    source_artifact = artifact()
    source_metadata = {"nested": {"labels": ["original"]}}
    artifacts = [source_artifact]
    result = message(artifacts=artifacts, metadata=source_metadata)
    source_artifact.content["steps"].append("changed")
    artifacts.clear()
    source_metadata["nested"]["labels"].append("changed")
    assert result.artifacts[0].content == {"steps": ["implement", "test"]}
    assert result.metadata == {"nested": {"labels": ["original"]}}


def test_defaults_are_not_shared():
    first, second = message(), message()
    first.metadata["x"] = True
    assert second.metadata == {}
    first_artifact, second_artifact = artifact(), artifact()
    first_artifact.metadata["x"] = True
    assert second_artifact.metadata == {}
    assert first_artifact.artifact_id != second_artifact.artifact_id


@pytest.mark.parametrize("kind", list(ArtifactType))
def test_artifact_types_creation_metadata_and_round_trip(kind):
    value = artifact(artifact_type=kind, metadata={"language": "python"})
    assert value.artifact_type is kind
    assert value.metadata == {"language": "python"}
    assert Artifact.model_validate_json(value.model_dump_json()) == value


def test_artifact_input_copy():
    content, metadata = {"patch": ["line"]}, {"tags": ["code"]}
    value = artifact(content=content, metadata=metadata)
    content["patch"].append("changed")
    metadata["tags"].append("changed")
    assert value.content == {"patch": ["line"]}
    assert value.metadata == {"tags": ["code"]}


@pytest.mark.parametrize("field,value", [
    ("artifact_id", "invalid"), ("artifact_type", "BLOB"),
    ("name", " "), ("content", object()), ("content", float("inf")),
    ("metadata", {"invalid": object()}),
])
def test_artifact_validation(field, value):
    with pytest.raises(ValidationError):
        artifact(**{field: value})


def test_fields_frozen_and_extra_fields_rejected():
    with pytest.raises(ValidationError):
        message().sender_agent_id = "forged"
    with pytest.raises(ValidationError):
        artifact().artifact_id = uuid4()
    with pytest.raises(ValidationError):
        message(approved=True)


@pytest.mark.parametrize("name", list(CommunicationEventName))
def test_future_telemetry_contract(name):
    original = message()
    event = CommunicationEvent(
        event_name=name, task_id=original.task_id, message_id=original.message_id,
    )
    assert event.component == "agent"
    assert event.timestamp.utcoffset() == timedelta(0)
    assert CommunicationEvent.model_validate_json(event.model_dump_json()) == event
    assert "content" not in event.model_dump()
    assert "metadata" not in event.model_dump()


@pytest.mark.parametrize("extra", ["content", "artifacts", "metadata"])
def test_telemetry_rejects_payload(extra):
    with pytest.raises(ValidationError):
        CommunicationEvent(event_name="agent.message.sent", task_id=uuid4(),
                           message_id=uuid4(), **{extra: "secret"})


def test_telemetry_rejects_unknown_event_and_naive_time():
    for changes in ({"event_name": "agent.message.command"},
                    {"timestamp": datetime(2026, 1, 1)}):
        values = dict(event_name="agent.message.sent", task_id=uuid4(), message_id=uuid4())
        with pytest.raises(ValidationError):
            CommunicationEvent(**(values | changes))


def test_import_has_no_execution_or_persistence_dependencies():
    script = """
import sys
from app.agents.communication import AgentMessage, Artifact, CommunicationEvent
blocked = ('app.agents.runtime', 'app.executions', 'app.approvals',
           'app.approved_execution', 'app.protected_execution', 'app.workflows',
           'app.tools', 'app.db', 'app.tasks', 'app.observability',
           'langgraph', 'sqlalchemy')
assert not any(name.startswith(blocked) for name in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script], capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stderr

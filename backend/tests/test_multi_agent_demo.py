"""Scripted demo, real PostgreSQL Task/Approval/Ledger/checkpoint integration."""
import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from test_approval_decision import engine
from app.agents.communication import Artifact, ArtifactType, AgentMessage, MessageType
from app.agents.models import Agent
from app.agents.runtime import AgentRuntime
from app.db.models import TaskRecord, ToolExecutionRecord, ApprovalRecord
from app.demos.coordinator import DemoCoordinator
from app.demos.fixture import PATCH, ScriptedDemoLLM, StageSamplePatch
from app.llm.schemas import ChatMessage
from app.tools.exceptions import ToolPermissionDenied, ToolInputValidationError
from app.tools.permission import tool_permission_context, current_tool_agent


def all_rows(engine, model):
    with Session(engine) as session:
        return session.scalars(select(model)).all()


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_demo_real_postgres_human_decision_and_artifact_chain(engine, decision):
    baseline = {model: {row.id for row in all_rows(engine, model)}
                for model in (TaskRecord, ApprovalRecord, ToolExecutionRecord)}

    def rows(engine, model):
        return [row for row in all_rows(engine, model) if row.id not in baseline[model]]

    output = []
    demo = DemoCoordinator(os.environ["DATABASE_URL"], sessionmaker(engine), output=output.append)
    runtimes, resumes = [], []
    original_run, original_resume = AgentRuntime.run, AgentRuntime.resume

    def run(runtime, *args, **kwargs):
        runtimes.append((runtime, current_tool_agent().name))
        return original_run(runtime, *args, **kwargs)

    def resume(runtime, **kwargs):
        assert current_tool_agent() is None
        resumes.append(runtime)
        return original_resume(runtime, **kwargs)

    def choose():
        assert rows(engine, TaskRecord)[0].status == "WAITING_APPROVAL"
        assert rows(engine, ApprovalRecord)[0].status == "PENDING"
        assert rows(engine, ToolExecutionRecord) == demo.effects == []
        return decision

    with patch.object(AgentRuntime, "run", run), patch.object(AgentRuntime, "resume", resume):
        result = demo.run(choose)
    request, response = result.messages[:2]
    assert request.message_type is MessageType.REQUEST
    assert response.metadata["in_reply_to"] == str(request.message_id)
    assert request.task_id == response.task_id == result.developer_task_id
    assert response.sender_agent_id == "developer" and response.receiver_agent_id == "supervisor"
    assert len(rows(engine, ApprovalRecord)) == 1
    if decision == "reject":
        assert result.status == "REJECTED" and response.message_type is MessageType.ERROR
        assert response.metadata["task_status"] == "REJECTED"
        assert result.artifacts == [] and result.tester_task_id is None
        assert result.staged_effect_count == 0 and demo.effects == []
        assert rows(engine, ToolExecutionRecord) == [] and resumes == []
        assert [role for _, role in runtimes] == ["developer"]
        assert rows(engine, TaskRecord)[0].status == "REJECTED"
        return
    assert result.status == "SUCCEEDED" and result.staged_effect_count == 1
    assert demo.effects == [{"owner_agent_id": "developer", "content": PATCH}]
    assert len(resumes) == 1 and resumes[0] is not runtimes[0][0]
    assert [role for _, role in runtimes] == ["developer", "tester"]
    assert all(task.status == "SUCCEEDED" for task in rows(engine, TaskRecord))
    assert len(rows(engine, ToolExecutionRecord)) == 1
    developer_artifact, report = result.artifacts
    assert developer_artifact.content == PATCH
    assert developer_artifact.metadata["owner_agent_id"] == "developer"
    tester_request, tester_result = result.messages[2:]
    assert tester_request.artifacts == (developer_artifact,)
    assert tester_request.metadata["in_reply_to"] == str(response.message_id)
    assert tester_result.metadata["in_reply_to"] == str(tester_request.message_id)
    assert tester_request.task_id == tester_result.task_id == result.tester_task_id
    assert tester_result.sender_agent_id == "tester" and tester_result.receiver_agent_id == "supervisor"
    assert report.artifact_type is ArtifactType.TEST_REPORT and report.content["status"] == "PASS"
    assert report.metadata["source_artifact_id"] == str(developer_artifact.artifact_id)
    assert report.metadata["owner_agent_id"] == "tester" and tester_result.artifacts == (report,)
    with demo.runtime("tester") as reader:
        state = reader.workflow_evidence(result.tester_task_id).values
        received = AgentMessage.model_validate_json(state["messages"][1]["content"])
        assert received.artifacts == (developer_artifact,)
        assert state["agent_identity"] == "tester"


def test_protected_sample_tool_permission_schema_and_memory_only_effect():
    effects = []
    tool = StageSamplePatch(effects)
    assert tool.metadata().side_effect_free is False
    tester = Agent(name="tester", role="TESTER", system_prompt="test")
    with tool_permission_context(tester), pytest.raises(ToolPermissionDenied):
        tool.execute({"change": "input_validation"})
    assert effects == []
    developer = Agent(name="developer", role="DEVELOPER", system_prompt="develop",
                      allowed_tools={tool.name})
    with tool_permission_context(developer), pytest.raises(ToolInputValidationError):
        tool.execute({"change": "arbitrary", "path": "elsewhere"})
    assert effects == []


def test_tester_fixture_reports_changed_artifact_as_failure():
    from uuid import uuid4
    artifact = Artifact(artifact_type=ArtifactType.CODE_PATCH, name="bad-patch",
        content={"before": PATCH["before"], "after": "wrong"}, metadata={"owner_agent_id": "developer"})
    request = AgentMessage(task_id=uuid4(), sender_agent_id="supervisor", receiver_agent_id="tester",
        message_type=MessageType.REQUEST, content="check", artifacts=(artifact,))
    result = ScriptedDemoLLM("tester").chat(messages=[ChatMessage(role="user", content=request.model_dump_json())], tools=[])
    import json
    report = json.loads(result.content)
    assert report["status"] == "FAIL" and not report["checks"]["expected_validation_patch"]


def test_demo_boundary_has_no_second_runtime_or_direct_tool_execution():
    root = Path(__file__).parents[1] / "app" / "demos"
    tree = ast.parse((root / "coordinator.py").read_text(encoding="utf-8"))
    assert {node.name for node in tree.body if isinstance(node, ast.ClassDef)} == {"DemoResult", "DemoCoordinator"}
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"eval", "exec", "open"} for node in ast.walk(tree))
    assert "ToolExecutor" not in ast.unparse(tree)
    assert "StateGraph" not in ast.unparse(tree)

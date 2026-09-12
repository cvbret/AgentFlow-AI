"""TASK-038 one-shot delegation, including the real existing graph boundary."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.models import Agent
from app.agents.registry import AgentRegistry
from app.agents.exceptions import AgentNotFoundError
from app.agents.communication import MessageType, CommunicationEvent
from app.agents.supervisor import create_supervisor, select_worker, delegate_task


def registry():
    result = AgentRegistry()
    result.register(Agent(name="developer", role="DEVELOPER", system_prompt="Develop carefully."))
    return result


def test_supervisor_is_existing_entity():
    agent = create_supervisor()
    assert type(agent) is Agent
    assert agent.role == "SUPERVISOR"
    assert agent.allowed_tools == frozenset()


def test_fixed_route_does_not_choose_first_registered_agent():
    agents = AgentRegistry()
    agents.register(Agent(name="tester", role="TESTER", system_prompt="Test."))
    worker = registry().get("developer")
    agents.register(worker)
    assert select_worker(agents) is worker


def test_missing_worker_fails_closed():
    with pytest.raises(AgentNotFoundError):
        select_worker(AgentRegistry())


def test_request_result_and_single_runtime_invocation():
    runtime = Mock()
    runtime.run.return_value = SimpleNamespace(content="Implemented.")
    task_id = uuid4()
    exchange = delegate_task(supervisor=create_supervisor(), registry=registry(),
                             runtime=runtime, task_id=task_id, content="Add validation.")
    assert exchange.request.message_type is MessageType.REQUEST
    assert exchange.request.sender_agent_id == "supervisor"
    assert exchange.request.receiver_agent_id == "developer"
    assert exchange.result.message_type is MessageType.RESULT
    assert exchange.result.sender_agent_id == "developer"
    assert exchange.result.receiver_agent_id == "supervisor"
    assert exchange.result.task_id == exchange.request.task_id == task_id
    assert exchange.result.metadata["in_reply_to"] == str(exchange.request.message_id)
    assert exchange.result.message_id != exchange.request.message_id
    assert exchange.result.content == "Implemented."
    runtime.run.assert_called_once()
    messages = runtime.run.call_args.args[0]
    assert [(m.role, m.content) for m in messages] == [
        ("system", "Develop carefully."), ("user", "Add validation."),
    ]
    assert runtime.run.call_args.kwargs == {"task_id": task_id}
    runtime.close.assert_not_called()
    runtime.resume.assert_not_called()


@pytest.mark.parametrize("kind", ["supervisor", "worker", "self", "content"])
def test_invalid_delegation_never_calls_runtime(kind):
    runtime = Mock()
    agents = registry()
    supervisor = create_supervisor()
    content = "Work."
    if kind == "supervisor":
        supervisor = agents.get("developer")
    elif kind == "worker":
        agents = AgentRegistry()
        agents.register(Agent(name="developer", role="TESTER", system_prompt="Test."))
    elif kind == "self":
        supervisor = create_supervisor("developer")
    else:
        content = " "
    with pytest.raises((ValueError, ValidationError)):
        delegate_task(supervisor=supervisor, registry=agents, runtime=runtime,
                      task_id=uuid4(), content=content)
    runtime.run.assert_not_called()


@pytest.mark.parametrize("signal_type", ["failure", "approval"])
def test_errors_and_approval_signal_propagate_without_retry(signal_type):
    error = RuntimeError("failed")
    if signal_type == "approval":
        from app.approvals.models import Approval
        from app.protected_execution import ApprovalRequired
        error = ApprovalRequired(Approval(task_id=uuid4(), tool_call_id="call",
                                         tool_name="protected", arguments={}))
    runtime = Mock()
    runtime.run.side_effect = error
    with pytest.raises(type(error)) as caught:
        delegate_task(supervisor=create_supervisor(), registry=registry(),
                      runtime=runtime, task_id=uuid4(), content="Work.")
    assert caught.value is error
    runtime.run.assert_called_once()
    runtime.resume.assert_not_called()
    runtime.close.assert_not_called()


def test_real_runtime_uses_existing_langgraph():
    from app.agents.runtime import AgentRuntime
    from app.llm.schemas import LLMResponse
    from app.tools.registry import ToolRegistry

    client = Mock()
    client.chat.return_value = LLMResponse(content="Worker result.")
    runtime = AgentRuntime(client, ToolRegistry())
    exchange = delegate_task(supervisor=create_supervisor(), registry=registry(),
                             runtime=runtime, task_id=uuid4(), content="Implement.")
    assert exchange.result.content == "Worker result."
    client.chat.assert_called_once()
    assert client.chat.call_args.kwargs["messages"][0].content == "Develop carefully."
    client.close.assert_not_called()


def test_supervisor_source_has_no_execution_imports_or_loops():
    import app.agents.supervisor as module
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name and name.startswith(
        ("app.tools", "app.approvals", "app.executions", "app.workflows",
         "app.protected_execution", "app.approved_execution", "app.tasks")
    ) for name in modules)
    assert not any(isinstance(node, (ast.For, ast.While, ast.AsyncFor)) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.ClassDef) and node.name in (
        "Supervisor", "SupervisorRuntime", "MultiAgentRuntime", "AgentExecutor"
    ) for node in ast.walk(tree))


@pytest.mark.parametrize("name", ["agent.delegation.started", "agent.delegation.completed"])
def test_future_delegation_event_names(name):
    event = CommunicationEvent(event_name=name, task_id=uuid4(), message_id=uuid4())
    assert event.event_name.value == name
    assert "content" not in event.model_dump()

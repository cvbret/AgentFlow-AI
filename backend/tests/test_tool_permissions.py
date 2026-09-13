"""Agent grants are checked at real Tool boundaries, including graph workers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest

from app.agents.models import Agent
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.agents.supervisor import create_supervisor, delegate_task
from app.approved_execution import ApprovedToolExecutionService
from app.executions.recovery import ExecutionRecoveryService
from app.executions.models import ExecutionStatus
from app.approvals.models import Approval
from app.llm.schemas import ToolCall, LLMResponse, ChatMessage
from app.observability import InMemoryObservabilitySink, use_sink
from app.protected_execution import ProtectedToolExecutionService, ApprovalRequired
from app.tools.executor import ToolExecutor
from app.tools.exceptions import ToolPermissionDenied, ToolExecutionError
from app.tools.implementations.calculator import CalculatorTool
from app.tools.permission import tool_permission_context
from app.tools.registry import ToolRegistry


def agent(grants=(), role="DEVELOPER", name="developer"):
    return Agent(name=name, role=role, system_prompt="Work", allowed_tools=frozenset(grants))


def call(name="calculator"):
    return ToolCall(id="call_1", name=name, arguments={"operation":"multiply", "a":123, "b":456})


class Probe(CalculatorTool):
    def __init__(self):
        super().__init__()
        self.effects = 0

    def _execute(self, data):
        self.effects += 1
        return super()._execute(data)


def tools(tool=None):
    registry = ToolRegistry()
    tool = tool or Probe()
    registry.register(tool)
    return registry, tool


@pytest.mark.parametrize("entry", ["executor", "protected", "direct"])
@pytest.mark.parametrize("allowed", [True, False])
def test_permission_precedes_execution(entry, allowed):
    registry, tool = tools()
    with tool_permission_context(agent(["calculator"] if allowed else [])):
        def execute():
            if entry == "executor": return ToolExecutor(registry).execute(call())
            if entry == "protected": return ProtectedToolExecutionService(registry).execute(task_id=uuid4(), tool_call=call())
            return tool.execute(call().arguments)
        if allowed:
            assert execute().content == "56088.0"
        else:
            with pytest.raises(ToolPermissionDenied) as error: execute()
            assert error.value.agent_name == "developer"
            assert error.value.tool_name == "calculator"
            assert not isinstance(error.value, ToolExecutionError)
    assert tool.effects == int(allowed)


def test_denial_precedes_lookup_and_input_validation():
    registry = Mock()
    with tool_permission_context(agent()), pytest.raises(ToolPermissionDenied):
        ToolExecutor(registry).execute(ToolCall(id="x", name="database_delete", arguments={"secret":"private"}))
    registry.get.assert_not_called()


def test_grant_does_not_bypass_hitl():
    registry, tool = tools()
    tool.side_effect_free = False
    with tool_permission_context(agent(["calculator"])), pytest.raises(ApprovalRequired):
        ProtectedToolExecutionService(registry).execute(task_id=uuid4(), tool_call=call())
    assert tool.effects == 0


def test_denied_protected_tool_does_not_request_approval():
    registry, tool = tools()
    tool.side_effect_free = False
    with tool_permission_context(agent()), pytest.raises(ToolPermissionDenied):
        ProtectedToolExecutionService(registry).execute(task_id=uuid4(), tool_call=call())
    assert tool.effects == 0


@pytest.mark.parametrize("role", ["SUPERVISOR", "DEVELOPER", "TESTER"])
def test_all_agent_roles_use_same_policy(role):
    registry, tool = tools()
    with tool_permission_context(agent(role=role)), pytest.raises(ToolPermissionDenied):
        ToolExecutor(registry).execute(call())
    assert tool.effects == 0


@pytest.mark.parametrize("recovery", [False, True])
def test_denial_precedes_approval_ledger_and_cache_access(recovery):
    registry, tool = tools()
    approval_loader, ledger = Mock(), Mock()
    cls = ExecutionRecoveryService if recovery else ApprovedToolExecutionService
    service = cls(registry, approval_loader, ledger)
    args = dict(task_id=uuid4(), approval_id=uuid4(), tool_call=call())
    with tool_permission_context(agent()), pytest.raises(ToolPermissionDenied):
        if recovery: service.recover(**args, stale_before=datetime.now(timezone.utc))
        else: service.execute(**args)
    approval_loader.assert_not_called()
    assert not ledger.mock_calls
    assert tool.effects == 0


def test_allowed_approved_execution_preserves_ledger_cache():
    registry, tool = tools()
    tool.side_effect_free = False
    approval = Approval(task_id=uuid4(), tool_call_id=call().id, tool_name="calculator", arguments=call().arguments)
    approval.approve()
    ledger = Mock()
    ledger.get.return_value = None
    ledger.claim.side_effect = lambda candidate: (candidate, True)
    service = ApprovedToolExecutionService(registry, lambda _: approval, ledger)
    args = dict(task_id=approval.task_id, approval_id=approval.id, tool_call=call())
    with tool_permission_context(agent(["calculator"])):
        assert service.execute(**args).content == "56088.0"
        saved = ledger.finish.call_args.args[0]
        assert saved.status is ExecutionStatus.SUCCEEDED
        ledger.get.return_value = saved
        assert service.execute(**args).content == "56088.0"
    assert tool.effects == 1
    assert ledger.claim.call_count == 1
    with tool_permission_context(agent()), pytest.raises(ToolPermissionDenied): service.execute(**args)
    assert tool.effects == 1


def runtime_with_tool():
    registry, tool = tools()
    llm = Mock()
    llm.chat.side_effect = [LLMResponse(tool_calls=[call()]), LLMResponse(content="done")]
    return AgentRuntime(llm, registry), tool, llm


@pytest.mark.parametrize("allowed", [True, False])
def test_real_langgraph_runtime_obeys_tool_context(allowed):
    runtime, tool, llm = runtime_with_tool()
    try:
        with tool_permission_context(agent(["calculator"] if allowed else [])):
            if allowed:
                assert runtime.run([ChatMessage(role="user",content="calculate")],task_id=uuid4()).content == "done"
            else:
                with pytest.raises(ToolPermissionDenied):
                    runtime.run([ChatMessage(role="user",content="calculate")],task_id=uuid4())
        assert tool.effects == int(allowed)
        assert llm.chat.call_count == (2 if allowed else 1)
    finally: runtime.close()


@pytest.mark.parametrize("allowed", [True, False])
def test_supervisor_passes_worker_grants_not_its_own(allowed):
    runtime, tool, _ = runtime_with_tool()
    registry = AgentRegistry()
    registry.register(agent(["calculator"] if allowed else []))
    supervisor = agent([] if allowed else ["calculator"], role="SUPERVISOR", name="supervisor")
    try:
        with tool_permission_context(supervisor):
            args = dict(supervisor=supervisor, registry=registry, runtime=runtime, task_id=uuid4(), content="calculate")
            if allowed: assert delegate_task(**args).result.content == "done"
            else:
                with pytest.raises(ToolPermissionDenied): delegate_task(**args)
        assert tool.effects == int(allowed)
    finally: runtime.close()


def test_nested_scope_restores_identity_after_error():
    registry, _ = tools()
    executor = ToolExecutor(registry)
    with tool_permission_context(agent()):
        with pytest.raises(RuntimeError):
            with tool_permission_context(agent(["calculator"])):
                executor.execute(call())
                raise RuntimeError("interrupt")
        with pytest.raises(ToolPermissionDenied): executor.execute(call())
    # Legacy non-Agent direct callers retain their previous contract.
    assert executor.execute(call()).content == "56088.0"


def test_parallel_invocations_do_not_share_agent_grants():
    barrier = Barrier(2)
    def run(allowed):
        registry, tool = tools()
        with tool_permission_context(agent(["calculator"] if allowed else [])):
            barrier.wait(timeout=5)
            try: ToolExecutor(registry).execute(call())
            except ToolPermissionDenied: assert not allowed
        return tool.effects
    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(run, [True,False])) == [1,0]


def test_denied_event_has_no_payload_or_agent_metadata():
    sink = InMemoryObservabilitySink()
    registry, _ = tools()
    with use_sink(sink), tool_permission_context(agent()), pytest.raises(ToolPermissionDenied):
        ToolExecutor(registry).execute(call())
    event = sink.events[0]
    assert event.event_name == "tool.permission.denied"
    assert event.attributes == {"tool_name":"calculator", "exception_type":"ToolPermissionDenied"}
    assert "123" not in str(event.attributes)


def test_broken_telemetry_cannot_authorize_execution():
    registry, tool = tools()
    sink = Mock()
    sink.emit.side_effect = RuntimeError("broken")
    with use_sink(sink), tool_permission_context(agent()), pytest.raises(ToolPermissionDenied):
        ToolExecutor(registry).execute(call())
    assert tool.effects == 0


def test_explicit_invalid_context_cannot_clear_identity():
    with pytest.raises(TypeError):
        with tool_permission_context(None): pass

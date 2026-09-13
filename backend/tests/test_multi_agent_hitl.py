"""TASK-040: real PostgreSQL delegation/HITL integration."""
import os
from unittest.mock import Mock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from test_approval_decision import engine
from test_task_resume import call, pending, decide
from test_recovery import age, recovery, loaded
from app.agents.models import Agent
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.agents.supervisor import create_supervisor
from app.agents.communication import MessageType
from app.approved_execution import ResumeAuthorizationError
from app.approvals.service import ApprovalDecisionConflictError
from app.approvals.repository import ApprovalRepository
from app.db.models import ApprovalRecord, ToolExecutionRecord, TaskRecord
from app.executions.repository import ExecutionRepository
from app.llm.schemas import LLMResponse
from app.tasks.delegation import execute_delegated_task, read_delegation_result
from app.tasks.models import TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.pause_persistence import HITLPausePersistence
from app.tasks.service import TaskExecutionService
from app.tasks.recovery import RecoveryOutcome
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry
from app.tools.permission import current_tool_agent
from app.tools.exceptions import ToolPermissionDenied
from app.workflows.checkpoint import open_checkpointer


def definitions(allowed=True):
    agents = AgentRegistry()
    agents.register(Agent(name="developer", role="DEVELOPER", system_prompt="Develop safely",
                          allowed_tools={"protected"} if allowed else set()))
    return agents


def make_runtime(engine, effects, responses, agents):
    class Protected(CalculatorTool):
        name = "protected"
        side_effect_free = False

        def _execute(self, data):
            effects.append(current_tool_agent().name)
            return super()._execute(data)

    tools = ToolRegistry()
    tools.register(Protected())
    llm = Mock()
    llm.chat.side_effect = responses

    def load(identity):
        with Session(engine) as session:
            return ApprovalRepository(session).get_by_id(identity)

    return AgentRuntime(llm, tools,
        checkpointer_factory=lambda: open_checkpointer(os.environ["DATABASE_URL"]),
        approval_loader=load, execution_repository=ExecutionRepository(lambda: Session(engine)),
        agent_loader=agents.get), llm


def start(engine, runtime, agents):
    with Session(engine) as session:
        service = TaskExecutionService(TaskRepository(session), lambda: runtime,
                                       HITLPausePersistence(session))
        # Supervisor grants must never be inherited by its Worker.
        supervisor = create_supervisor().model_copy(update={"allowed_tools": frozenset({"protected"})})
        return execute_delegated_task(service, supervisor=supervisor, registry=agents,
                                      task_input="Implement calculation")


def reply(engine, runtime, request):
    with Session(engine) as session:
        return read_delegation_result(request, session=session, runtime=runtime)


def rows(engine, model):
    with Session(engine) as session:
        return session.scalars(select(model)).all()


def pause(engine, effects):
    agents = definitions()
    first, llm = make_runtime(engine, effects, [LLMResponse(tool_calls=[call(2, True)])], agents)
    try:
        task, request = start(engine, first, agents)
        assert task.status is TaskStatus.WAITING_APPROVAL
        assert reply(engine, first, request) is None
        assert effects == [] and rows(engine, ToolExecutionRecord) == []
        llm.chat.assert_called_once()
        return task, request, pending(engine, task.id)
    finally:
        first.close()


def test_approve_fresh_runtime_worker_result_and_no_duplicate_effect(engine):
    effects = []
    task, request, approval = pause(engine, effects)
    runtime, llm = make_runtime(engine, effects, [LLMResponse(content="implemented")], definitions())
    try:
        assert current_tool_agent() is None
        with Session(engine) as session:
            decide(session, approval.id, runtime=runtime)
        result = reply(engine, runtime, request)
        assert result.message_type is MessageType.RESULT and result.content == "implemented"
        assert result.sender_agent_id == "developer" and result.receiver_agent_id == "supervisor"
        assert result.task_id == task.id and result.metadata["in_reply_to"] == str(request.message_id)
        assert loaded(engine, task.id).status is TaskStatus.SUCCEEDED
        ledger = rows(engine, ToolExecutionRecord)
        assert len(ledger) == len(rows(engine, ApprovalRecord)) == 1
        identity = (ledger[0].id, ledger[0].idempotency_key)
        with Session(engine) as session, pytest.raises(ApprovalDecisionConflictError):
            decide(session, approval.id, runtime=runtime)
        with patch.object(runtime._approved_execution._executions, "claim", wraps=runtime._approved_execution._executions.claim) as claim:
            runtime._approved_execution.execute(approval_id=approval.id, task_id=task.id, tool_call=call(2, True))
            claim.assert_not_called()
        again = rows(engine, ToolExecutionRecord)
        assert len(again) == 1 and (again[0].id, again[0].idempotency_key) == identity
        assert effects == ["developer"] and current_tool_agent() is None
        llm.chat.assert_called_once()
    finally:
        runtime.close()


def test_reject_is_rejected_without_execution_or_retry(engine):
    effects = []
    task, request, approval = pause(engine, effects)
    runtime, llm = make_runtime(engine, effects, [], definitions())
    try:
        with Session(engine) as session:
            decide(session, approval.id, "reject", runtime=runtime)
        assert loaded(engine, task.id).status is TaskStatus.REJECTED
        assert rows(engine, ApprovalRecord)[0].status == "REJECTED"
        result = reply(engine, runtime, request)
        assert result.message_type is MessageType.ERROR and result.metadata["task_status"] == "REJECTED"
        assert result.metadata["in_reply_to"] == str(request.message_id)
        assert effects == [] and rows(engine, ToolExecutionRecord) == []
        llm.chat.assert_not_called()
    finally:
        runtime.close()


def test_denied_worker_cannot_inherit_supervisor_grants_or_create_approval(engine):
    effects = []
    agents = definitions(False)
    runtime, _ = make_runtime(engine, effects, [LLMResponse(tool_calls=[call(2, True)])], agents)
    try:
        with pytest.raises(ToolPermissionDenied):
            start(engine, runtime, agents)
        assert rows(engine, ApprovalRecord) == rows(engine, ToolExecutionRecord) == effects == []
        assert rows(engine, TaskRecord)[0].status == "FAILED"
    finally:
        runtime.close()


def test_approval_cannot_override_policy_tightened_before_resume(engine):
    effects = []
    task, request, approval = pause(engine, effects)
    runtime, llm = make_runtime(engine, effects, [], definitions(False))
    try:
        with Session(engine) as session, pytest.raises(ToolPermissionDenied):
            decide(session, approval.id, runtime=runtime)
        assert rows(engine, ApprovalRecord)[0].status == "APPROVED"
        assert loaded(engine, task.id).status is TaskStatus.FAILED
        assert reply(engine, runtime, request).metadata["task_status"] == "FAILED"
        assert effects == [] and rows(engine, ToolExecutionRecord) == []
        llm.chat.assert_not_called()
    finally:
        runtime.close()


@pytest.mark.parametrize("cached", [False, True])
def test_existing_recovery_restores_worker_after_approval_dispatch_loss(engine, cached):
    effects = []
    task, request, approval = pause(engine, effects)
    with Session(engine) as session:
        decide(session, approval.id, callback=lambda *args: None)
    age(engine, task.id)
    runtime, _ = make_runtime(engine, effects, [LLMResponse(content="recovered")], definitions())
    try:
        if cached:
            runtime._approved_execution.execute(approval_id=approval.id, task_id=task.id, tool_call=call(2, True))
            assert effects == ["developer"]
        age(engine, task.id)  # Stale Ledger as well as Task; preserve live-owner protection.
        assert recovery(engine, runtime).recover(task.id).outcome is RecoveryOutcome.RECOVERED
        assert reply(engine, runtime, request).content == "recovered"
        assert effects == ["developer"] and len(rows(engine, ToolExecutionRecord)) == 1
    finally:
        runtime.close()


def test_direct_completion_and_reply_provenance_validation(engine):
    effects = []
    agents = definitions()
    runtime, llm = make_runtime(engine, effects, [LLMResponse(content="done")], agents)
    try:
        task, request = start(engine, runtime, agents)
        assert task.status is TaskStatus.SUCCEEDED
        assert reply(engine, runtime, request).content == "done"
        for update in ({"receiver_agent_id": "other"}, {"content": "other"}):
            with pytest.raises(ResumeAuthorizationError):
                reply(engine, runtime, request.model_copy(update=update))
        with pytest.raises(ValueError):
            reply(engine, runtime, request.model_copy(update={"message_type": MessageType.RESULT}))
        llm.chat.assert_called_once()
        assert effects == []
    finally:
        runtime.close()


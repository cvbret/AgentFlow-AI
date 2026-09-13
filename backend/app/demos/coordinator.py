"""Fixed demo composition of existing services; no durable coordinator state."""
import json
from collections.abc import Callable
from contextlib import contextmanager
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.communication import AgentMessage, Artifact, ArtifactType, MessageType
from app.agents.models import Agent
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.agents.supervisor import create_supervisor
from app.approvals.continuation_persistence import ApprovalContinuationPersistence
from app.approvals.rejection_persistence import ApprovalRejectionPersistence
from app.approvals.repository import ApprovalRepository
from app.approvals.service import ApprovalDecisionService
from app.db.models import ApprovalRecord
from app.demos.fixture import USER_REQUEST, ScriptedDemoLLM, StageSamplePatch
from app.executions.repository import ExecutionRepository
from app.llm.schemas import ChatMessage
from app.tasks.delegation import execute_delegated_task, read_delegation_result
from app.tasks.models import TaskStatus
from app.tasks.pause_persistence import HITLPausePersistence
from app.tasks.repository import TaskRepository
from app.tasks.resume import TaskResumeService
from app.tasks.service import TaskExecutionService
from app.tools.permission import tool_permission_context
from app.tools.registry import ToolRegistry
from app.workflows.checkpoint import open_checkpointer


class DemoResult(BaseModel):
    """Volatile output DTO; Task/Approval/checkpoint remain durable authorities."""
    user_request: str = USER_REQUEST
    status: str
    developer_task_id: UUID
    approval_id: UUID
    tester_task_id: UUID | None = None
    messages: list[AgentMessage] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    staged_effect_count: int


class DemoCoordinator:
    def __init__(self, database_url: str, sessions: Callable[[], Session], *, output=print):
        self.database_url, self.sessions, self.output = database_url, sessions, output
        self.effects: list[dict] = []  # Volatile demo side effect, never an execution ledger.
        self.agents = AgentRegistry()
        self.agents.register(create_supervisor())
        self.agents.register(Agent(name="developer", role="DEVELOPER",
            system_prompt="Produce the fixed sample validation patch using the protected staging Tool.",
            allowed_tools={"stage_sample_patch"}))
        self.agents.register(Agent(name="tester", role="TESTER",
            system_prompt="Compare the supplied CODE_PATCH against known fixture acceptance conditions.",
            allowed_tools=set()))

    @contextmanager
    def runtime(self, role):
        registry = ToolRegistry()
        registry.register(StageSamplePatch(self.effects))

        def load(identity):
            with self.sessions() as session:
                return ApprovalRepository(session).get_by_id(identity)

        runtime = AgentRuntime(ScriptedDemoLLM(role), registry,
            checkpointer_factory=lambda: open_checkpointer(self.database_url),
            approval_loader=load, execution_repository=ExecutionRepository(self.sessions),
            agent_loader=self.agents.get)
        try:
            yield runtime
        finally:
            runtime.close()

    def service(self, session, runtime):
        return TaskExecutionService(TaskRepository(session), lambda: runtime, HITLPausePersistence(session))

    def run(self, decision: Callable[[], Literal["approve", "reject"]]) -> DemoResult:
        """One demo invocation. Human callback is called only after durable pause."""
        self.output(f"[User] {USER_REQUEST}")
        self.output("[Supervisor] Delegating to developer (scripted LLM fixture)")
        with self.runtime("developer") as runtime, self.sessions() as session:
            task, request = execute_delegated_task(self.service(session, runtime),
                supervisor=self.agents.get("supervisor"), registry=self.agents, task_input=USER_REQUEST)
        if task.status is not TaskStatus.WAITING_APPROVAL:
            raise RuntimeError("Demo expected a durable protected Tool pause")
        with self.sessions() as session:
            approval_id = session.scalars(select(ApprovalRecord.id).where(
                ApprovalRecord.task_id == task.id, ApprovalRecord.status == "PENDING")).one()
        self.output(f"[System] WAITING_APPROVAL task={task.id} approval={approval_id}")
        self.output("[Developer] Proposes stage_sample_patch: fixed greeting validation in volatile memory")
        choice = decision()
        if choice not in ("approve", "reject"):
            raise ValueError("Decision must be approve or reject; Task remains waiting")
        with self.runtime("developer") as fresh:
            with self.sessions() as session:
                ApprovalDecisionService(ApprovalRepository(session), TaskRepository(session),
                    ApprovalRejectionPersistence(session), ApprovalContinuationPersistence(session)
                ).decide(approval_id, choice)
            self.output(f"[Human] {'APPROVED' if choice == 'approve' else 'REJECTED'}")
            if choice == "approve":
                self.output("[System] Resuming durable workflow with fresh Runtime/Saver")
                with self.sessions() as session:
                    TaskResumeService(session, lambda: fresh).resume(task.id, approval_id)
            # Dedicated fresh read-only Session, as required by TASK-040.
            with self.sessions() as session:
                result = read_delegation_result(request, session=session, runtime=fresh)
        if result is None:
            raise RuntimeError("Demo did not reach a terminal Developer result")
        if result.message_type is MessageType.ERROR:
            return DemoResult(status=result.metadata["task_status"], developer_task_id=task.id,
                approval_id=approval_id, messages=[request, result], staged_effect_count=len(self.effects))
        patch = Artifact(artifact_type=ArtifactType.CODE_PATCH, name="greeting-validation",
            content=json.loads(result.content), metadata={"owner_agent_id": "developer", "task_id": str(task.id)})
        result = result.model_copy(update={"artifacts": (patch,)})
        self.output("[Developer] CODE_PATCH ready; handing artifact to Tester")
        tester = self.agents.get("tester")
        tester_requests = []

        def invoke(test_task, runtime):
            test_request = AgentMessage(task_id=test_task.id, sender_agent_id="supervisor",
                receiver_agent_id=tester.name, message_type=MessageType.REQUEST,
                content="Validate the Developer patch against the sample acceptance conditions.",
                artifacts=(patch,), metadata={"in_reply_to": str(result.message_id),
                    "developer_task_id": str(task.id)})
            tester_requests.append(test_request)
            with tool_permission_context(tester):
                return runtime.run([ChatMessage(role="system", content=tester.system_prompt),
                    ChatMessage(role="user", content=test_request.model_dump_json())], task_id=test_task.id)

        with self.runtime("tester") as runtime, self.sessions() as session:
            test_task = self.service(session, runtime).execute("Validate Developer artifact", invoke=invoke)
        if test_task.status is not TaskStatus.SUCCEEDED:
            raise RuntimeError("Tester did not finish successfully")
        report = Artifact(artifact_type=ArtifactType.TEST_REPORT, name="greeting-validation-report",
            content=json.loads(test_task.result), metadata={"owner_agent_id": tester.name,
                "task_id": str(test_task.id), "source_artifact_id": str(patch.artifact_id)})
        test_result = AgentMessage(task_id=test_task.id, sender_agent_id=tester.name,
            receiver_agent_id="supervisor", message_type=MessageType.RESULT, content=test_task.result,
            artifacts=(report,), metadata={"in_reply_to": str(tester_requests[0].message_id)})
        self.output(f"[Tester] TEST_REPORT {report.content['status']} (fixture comparison, not code execution)")
        return DemoResult(status="SUCCEEDED" if report.content["status"] == "PASS" else "FAILED",
            developer_task_id=task.id, tester_task_id=test_task.id, approval_id=approval_id,
            messages=[request, result, tester_requests[0], test_result], artifacts=[patch, report],
            staged_effect_count=len(self.effects))

"""Application glue for existing delegation and Task/HITL lifecycle services."""
from sqlalchemy.orm import Session

from app.agents.communication import AgentMessage, MessageType
from app.agents.models import Agent
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentResult, AgentRuntime
from app.agents.supervisor import delegate_task
from app.approved_execution import ResumeAuthorizationError
from app.tasks.models import Task, TaskStatus
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskExecutionService


def execute_delegated_task(
    service: TaskExecutionService, *, supervisor: Agent, registry: AgentRegistry,
    task_input: str, worker_name: str = "developer",
) -> tuple[Task, AgentMessage]:
    """Return the durable Task plus the caller-retained REQUEST, including on pause.

    The caller owns service/runtime resources and retains the request for reply
    correlation. No message store or second approval/lifecycle is introduced.
    """
    requests: list[AgentMessage] = []

    def invoke(task: Task, runtime: AgentRuntime) -> AgentResult:
        exchange = delegate_task(
            supervisor=supervisor, registry=registry, runtime=runtime,
            task_id=task.id, content=task.input, worker_name=worker_name,
            on_request=requests.append,
        )
        return AgentResult(content=exchange.result.content)

    task = service.execute(task_input, invoke=invoke)
    return task, requests[0]


def read_delegation_result(
    request: AgentMessage, *, session: Session, runtime: AgentRuntime,
) -> AgentMessage | None:
    """Project a fresh durable Task outcome into a reply; never run or approve.

    This is an internal, trusted-caller API, not user authorization. REQUEST is
    retained by that caller, not accepted as execution identity. Durable workflow
    provenance must agree with it. None means no terminal reply yet.
    """
    if request.message_type is not MessageType.REQUEST:
        raise ValueError("A delegation REQUEST is required")
    task = TaskRepository(session).get(request.task_id)
    session.rollback()  # No business transaction spans checkpoint access.
    if task is None or task.input != request.content:
        raise ResumeAuthorizationError("Delegation Task does not match request")
    evidence = runtime.workflow_evidence(task.id)
    state = evidence.values
    if (state.get("task_id") != str(task.id)
            or state.get("execution_mode") != "AGENT_BOUND"
            or state.get("agent_identity") != request.receiver_agent_id):
        raise ResumeAuthorizationError("Delegation provenance does not match request")
    if task.status is TaskStatus.SUCCEEDED:
        if evidence.next_nodes or state.get("final_answer") != task.result:
            raise ResumeAuthorizationError("Delegation completion is not reconciled")
        kind, content = MessageType.RESULT, task.result
    elif task.status is TaskStatus.REJECTED:
        kind, content = MessageType.ERROR, "Human rejected the protected operation."
    elif task.status is TaskStatus.FAILED:
        kind, content = MessageType.ERROR, "Worker execution failed."
    else:
        return None
    return AgentMessage(
        task_id=task.id, sender_agent_id=state["agent_identity"],
        receiver_agent_id=request.sender_agent_id, message_type=kind,
        content=content,
        metadata={"in_reply_to": str(request.message_id), "task_status": task.status.value},
    )

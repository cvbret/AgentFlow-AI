"""One-shot Supervisor delegation through the existing injected AgentRuntime."""
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from app.agents.models import Agent
from app.agents.registry import AgentRegistry
from app.agents.communication import AgentMessage, MessageType
from app.llm.schemas import ChatMessage

if TYPE_CHECKING:
    from app.agents.runtime import AgentRuntime


def create_supervisor(name: str = "supervisor") -> Agent:
    return Agent(
        name=name, role="SUPERVISOR",
        system_prompt="Delegate the task to the configured developer and return its result.",
    )


def select_worker(registry: AgentRegistry, worker_name: str = "developer") -> Agent:
    """A fixed named route, not content-based planning or scheduling."""
    worker = registry.get(worker_name)
    if worker.role != "DEVELOPER":
        raise ValueError("The configured worker must have role DEVELOPER")
    return worker


@dataclass(frozen=True)
class DelegationResult:
    request: AgentMessage
    result: AgentMessage


def delegate_task(
    *, supervisor: Agent, registry: AgentRegistry, runtime: "AgentRuntime",
    task_id: UUID, content: str, worker_name: str = "developer",
) -> DelegationResult:
    """Delegate exactly once; the caller owns task lifecycle and Runtime resources.

    This entry point does not enforce role tool grants or persist messages.
    Runtime errors/interrupt signals propagate unchanged. No retry or resume is
    attempted here, and a RESULT is constructed only after Runtime success.
    """
    if supervisor.role != "SUPERVISOR":
        raise ValueError("The delegating Agent must have role SUPERVISOR")
    worker = select_worker(registry, worker_name)
    if worker.name == supervisor.name:
        raise ValueError("Supervisor and worker must have distinct identities")
    request = AgentMessage(
        task_id=task_id, sender_agent_id=supervisor.name,
        receiver_agent_id=worker.name, message_type=MessageType.REQUEST,
        content=content,
    )
    output = runtime.run(
        [
            ChatMessage(role="system", content=worker.system_prompt),
            ChatMessage(role="user", content=request.content),
        ],
        task_id=request.task_id,
    )
    result = AgentMessage(
        task_id=request.task_id, sender_agent_id=worker.name,
        receiver_agent_id=supervisor.name, message_type=MessageType.RESULT,
        content=output.content,
        metadata={"in_reply_to": str(request.message_id)},
    )
    return DelegationResult(request=request, result=result)

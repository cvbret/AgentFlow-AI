from collections.abc import Callable
from threading import Lock

from app.agents.runtime import AgentRuntime
from app.core.config import get_settings
from app.llm.client import LLMClient
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


_agent_runtime: AgentRuntime | None = None
_agent_runtime_lock = Lock()


def build_agent_runtime() -> AgentRuntime:
    settings = get_settings()
    llm_client = LLMClient(settings=settings)
    tool_registry = ToolRegistry()
    tool_registry.register(CalculatorTool())
    return AgentRuntime(llm_client=llm_client, tool_registry=tool_registry)


def get_agent_runtime() -> AgentRuntime:
    global _agent_runtime
    runtime = _agent_runtime
    if runtime is not None:
        return runtime

    with _agent_runtime_lock:
        runtime = _agent_runtime
        if runtime is None:
            runtime = build_agent_runtime()
            _agent_runtime = runtime
        return runtime


def get_agent_runtime_provider() -> Callable[[], AgentRuntime]:
    return get_agent_runtime


def close_agent_runtime() -> None:
    global _agent_runtime
    with _agent_runtime_lock:
        runtime = _agent_runtime
        _agent_runtime = None
        if runtime is not None:
            runtime.close()

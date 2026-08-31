from app.llm.schemas import ToolCall
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolExecutionResult


class ToolExecutor:
    """Execute one provider-neutral ToolCall through a ToolRegistry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def execute(self, tool_call: ToolCall) -> ToolExecutionResult:
        tool = self._registry.get(tool_call.name)
        result = tool.execute(tool_call.arguments)
        return ToolExecutionResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=result.content,
        )

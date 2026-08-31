from app.tools.base import Tool
from app.tools.exceptions import DuplicateToolError, ToolError, ToolNotFoundError
from app.tools.schemas import ToolMetadata


class ToolRegistry:
    """In-memory registry for explicitly registered Tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not isinstance(tool, Tool):
            raise ToolError("Only Tool instances can be registered")
        if tool.name in self._tools:
            raise DuplicateToolError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool not found: {name}") from exc

    def list(self) -> list[ToolMetadata]:
        return [tool.metadata() for tool in self._tools.values()]

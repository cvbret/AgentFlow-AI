from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

from app.tools.exceptions import ToolError, ToolExecutionError, ToolInputValidationError
from app.tools.schemas import ToolMetadata, ToolResult


class Tool(ABC):
    """Minimal Tool contract with schema-backed input validation."""

    name: str
    description: str
    input_schema: type[BaseModel]
    side_effect_free: bool = False

    def __init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ToolError("Tool name must be a non-empty string")
        if any(character.isspace() for character in self.name):
            raise ToolError("Tool name must not contain whitespace")
        if not isinstance(self.description, str) or not self.description.strip():
            raise ToolError("Tool description must be a non-empty string")
        if not isinstance(self.input_schema, type) or not issubclass(
            self.input_schema, BaseModel
        ):
            raise ToolError("Tool input_schema must be a Pydantic model type")

    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema.model_json_schema(),
            side_effect_free=self.side_effect_free,
        )

    def execute(
        self,
        input_data: BaseModel | Mapping[str, Any],
    ) -> ToolResult:
        try:
            validated_input = self.input_schema.model_validate(input_data)
        except ValidationError as exc:
            raise ToolInputValidationError(
                f"Invalid input for Tool '{self.name}': {exc}"
            ) from exc

        try:
            result = self._execute(validated_input)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolExecutionError(
                f"Tool '{self.name}' execution failed"
            ) from exc

        if not isinstance(result, ToolResult):
            raise ToolExecutionError(
                f"Tool '{self.name}' returned an invalid ToolResult"
            )
        return result

    @abstractmethod
    def _execute(self, input_data: BaseModel) -> ToolResult:
        """Execute validated input in the concrete Tool implementation."""

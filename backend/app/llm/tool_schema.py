from collections.abc import Sequence
from typing import Any

from app.tools.schemas import ToolMetadata


class OpenAICompatibleToolSchemaAdapter:
    """Convert Tool domain metadata to provider-specific tool definitions."""

    @staticmethod
    def convert(metadata: ToolMetadata) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": metadata.name,
                "description": metadata.description,
                "parameters": metadata.input_schema,
            },
        }

    @classmethod
    def convert_many(
        cls,
        metadata: Sequence[ToolMetadata],
    ) -> list[dict[str, Any]]:
        return [cls.convert(item) for item in metadata]

from app.tools.exceptions import ToolExecutionError
from app.tools.schemas import ToolMetadata


class ToolExecutionPolicy:
    """Allow automatic execution only for explicitly safe Tool metadata."""

    def ensure_automatic_execution_allowed(
        self,
        metadata: ToolMetadata,
    ) -> None:
        if metadata.side_effect_free:
            return

        raise ToolExecutionError(
            f"Tool '{metadata.name}' cannot be automatically executed because "
            "it is not declared side-effect-free and no protected execution "
            "mechanism exists"
        )

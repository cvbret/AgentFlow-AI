import pytest
from pydantic import BaseModel, ValidationError

from app.tools.exceptions import (
    DuplicateToolError,
    ToolError,
    ToolExecutionError,
    ToolInputValidationError,
    ToolNotFoundError,
)
from app.tools.base import Tool
from app.tools.implementations.calculator import CalculatorInput, CalculatorTool
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolMetadata, ToolResult


@pytest.fixture
def calculator() -> CalculatorTool:
    return CalculatorTool()


@pytest.fixture
def registry(calculator: CalculatorTool) -> ToolRegistry:
    tool_registry = ToolRegistry()
    tool_registry.register(calculator)
    return tool_registry


@pytest.mark.parametrize(
    ("operation", "a", "b", "expected"),
    [
        ("add", 2, 3, "5.0"),
        ("subtract", 5, 3, "2.0"),
        ("multiply", 2, 3, "6.0"),
        ("divide", 6, 3, "2.0"),
    ],
)
def test_calculator_executes_basic_operations(
    calculator: CalculatorTool,
    operation: str,
    a: float,
    b: float,
    expected: str,
) -> None:
    result = calculator.execute({"operation": operation, "a": a, "b": b})

    assert result.content == expected


def test_calculator_rejects_invalid_operation(calculator: CalculatorTool) -> None:
    with pytest.raises(ToolInputValidationError, match="Invalid input"):
        calculator.execute({"operation": "power", "a": 2, "b": 3})


def test_calculator_rejects_divide_by_zero(calculator: CalculatorTool) -> None:
    with pytest.raises(ToolExecutionError, match="divide by zero"):
        calculator.execute({"operation": "divide", "a": 1, "b": 0})


def test_calculator_input_schema_rejects_invalid_role_like_input() -> None:
    with pytest.raises(ValidationError):
        CalculatorInput(operation="power", a=2, b=3)


def test_registry_registers_and_gets_tool(
    registry: ToolRegistry,
    calculator: CalculatorTool,
) -> None:
    assert registry.get("calculator") is calculator


def test_registry_rejects_duplicate_tool_name(
    registry: ToolRegistry,
    calculator: CalculatorTool,
) -> None:
    with pytest.raises(DuplicateToolError, match="already registered"):
        registry.register(calculator)


def test_registry_raises_for_missing_tool(registry: ToolRegistry) -> None:
    with pytest.raises(ToolNotFoundError, match="Tool not found: missing"):
        registry.get("missing")


def test_registry_lists_tool_metadata(registry: ToolRegistry) -> None:
    metadata = registry.list()

    assert len(metadata) == 1
    assert metadata[0].name == "calculator"
    assert metadata[0].description
    assert metadata[0].input_schema["properties"]["operation"]["enum"] == [
        "add",
        "subtract",
        "multiply",
        "divide",
    ]
    assert metadata[0].side_effect_free is True


def test_tool_metadata_defaults_to_side_effect_free_false() -> None:
    metadata = ToolMetadata(
        name="unknown",
        description="An unannotated tool",
        input_schema={"type": "object"},
    )

    assert metadata.side_effect_free is False


def test_unannotated_tool_metadata_defaults_to_side_effect_free_false() -> None:
    class UnannotatedTool(Tool):
        name = "unannotated"
        description = "An unannotated tool"
        input_schema = CalculatorInput

        def _execute(self, input_data: BaseModel) -> ToolResult:
            return ToolResult(content="ok")

    assert UnannotatedTool().metadata().side_effect_free is False


def test_registry_preserves_side_effect_metadata(calculator: CalculatorTool) -> None:
    registry = ToolRegistry()
    registry.register(calculator)

    assert registry.list()[0].side_effect_free is True


def test_tool_name_must_not_be_empty() -> None:
    class InvalidNameTool(CalculatorTool):
        name = ""

    with pytest.raises(ToolError, match="non-empty"):
        InvalidNameTool()

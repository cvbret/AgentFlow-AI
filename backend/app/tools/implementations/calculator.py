from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from app.tools.base import Tool
from app.tools.exceptions import ToolExecutionError
from app.tools.schemas import ToolResult


class CalculatorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["add", "subtract", "multiply", "divide"]
    a: float
    b: float


class CalculatorTool(Tool):
    name = "calculator"
    description = "Perform one basic arithmetic operation on two numbers."
    input_schema = CalculatorInput
    side_effect_free = True

    def _execute(self, input_data: BaseModel) -> ToolResult:
        calculator_input = cast(CalculatorInput, input_data)

        if calculator_input.operation == "add":
            result = calculator_input.a + calculator_input.b
        elif calculator_input.operation == "subtract":
            result = calculator_input.a - calculator_input.b
        elif calculator_input.operation == "multiply":
            result = calculator_input.a * calculator_input.b
        elif calculator_input.operation == "divide":
            if calculator_input.b == 0:
                raise ToolExecutionError("Calculator cannot divide by zero")
            result = calculator_input.a / calculator_input.b
        else:
            raise ToolExecutionError(
                f"Unsupported calculator operation: {calculator_input.operation}"
            )

        return ToolResult(content=str(result))

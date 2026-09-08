import json
from uuid import uuid4

import httpx
import pytest

from app.agents.runtime import AgentMaxStepsExceededError, AgentRuntime
from app.core.config import Settings
from app.llm.client import (
    InvalidLLMResponseError,
    LLMClient,
    LLMProviderError,
)
from app.llm.schemas import ChatMessage
from app.tools.exceptions import (
    ToolExecutionError,
    ToolInputValidationError,
    ToolNotFoundError,
)
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


def make_settings(*, max_attempts: int = 3) -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="test-api-key",
        llm_base_url="https://llm.example.com/v1",
        llm_model="test-model",
        llm_max_attempts=max_attempts,
    )


def make_registry(calculator: CalculatorTool | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(calculator or CalculatorTool())
    return registry


def make_tool_response(
    *calls: tuple[str, str, str],
    content: str | None = None,
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": content,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": arguments},
                        }
                        for call_id, name, arguments in calls
                    ],
                }
            }
        ]
    }


def make_runtime(
    responses: list[dict[str, object]],
    captured_payloads: list[dict[str, object]] | None = None,
    *,
    status_code: int = 200,
    max_steps: int = 5,
    max_attempts: int = 3,
    calculator: CalculatorTool | None = None,
) -> AgentRuntime:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured_payloads is not None:
            captured_payloads.append(json.loads(request.content))
        response = responses.pop(0)
        return httpx.Response(status_code, json=response, request=request)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = LLMClient(
        settings=make_settings(max_attempts=max_attempts),
        http_client=http_client,
    )
    return AgentRuntime(
        client,
        make_registry(calculator),
        max_steps=max_steps,
    )


def test_runtime_returns_direct_final_answer() -> None:
    runtime = make_runtime(
        [{"choices": [{"message": {"content": "Direct answer"}}]}]
    )

    result = runtime.run(
        [ChatMessage(role="user", content="Hello")],
        task_id=uuid4(),

    )

    assert result.content == "Direct answer"


def test_runtime_executes_one_tool_call_then_returns_final_answer() -> None:
    payloads: list[dict[str, object]] = []
    runtime = make_runtime(
        [
            make_tool_response(
                ("call_1", "calculator", '{"operation":"multiply","a":12,"b":8}')
            ),
            {"choices": [{"message": {"content": "The answer is 96."}}]},
        ],
        payloads,
    )

    result = runtime.run(
        [ChatMessage(role="user", content="Calculate 12 times 8")],
        task_id=uuid4(),

    )

    assert result.content == "The answer is 96."
    assert len(payloads) == 2
    assert payloads[1]["messages"][-2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "arguments": '{"operation":"multiply","a":12,"b":8}',
                    },
                }
            ],
        },
        {"role": "tool", "content": "96.0", "tool_call_id": "call_1"},
    ]


def test_runtime_supports_two_tool_rounds() -> None:
    payloads: list[dict[str, object]] = []
    runtime = make_runtime(
        [
            make_tool_response(
                ("call_1", "calculator", '{"operation":"add","a":2,"b":3}')
            ),
            make_tool_response(
                ("call_2", "calculator", '{"operation":"multiply","a":5,"b":4}')
            ),
            {"choices": [{"message": {"content": "Final: 20"}}]},
        ],
        payloads,
    )

    result = runtime.run(
        [ChatMessage(role="user", content="Calculate in steps")],
        task_id=uuid4(),

    )

    assert result.content == "Final: 20"
    assert len(payloads) == 3
    assert payloads[2]["messages"][-2]["tool_calls"][0]["id"] == "call_2"
    assert payloads[2]["messages"][-1] == {
        "role": "tool",
        "content": "20.0",
        "tool_call_id": "call_2",
    }


def test_runtime_executes_multiple_tool_calls_sequentially() -> None:
    payloads: list[dict[str, object]] = []
    runtime = make_runtime(
        [
            make_tool_response(
                ("call_1", "calculator", '{"operation":"add","a":2,"b":3}'),
                ("call_2", "calculator", '{"operation":"subtract","a":9,"b":4}'),
            ),
            {"choices": [{"message": {"content": "Results: 5 and 5"}}]},
        ],
        payloads,
    )

    result = runtime.run(
        [ChatMessage(role="user", content="Do both calculations")],
        task_id=uuid4(),

    )

    assert result.content == "Results: 5 and 5"
    assert payloads[1]["messages"][-2:] == [
        {"role": "tool", "content": "5.0", "tool_call_id": "call_1"},
        {"role": "tool", "content": "5.0", "tool_call_id": "call_2"},
    ]


def test_runtime_raises_when_max_steps_are_exceeded() -> None:
    runtime = make_runtime(
        [
            make_tool_response(
                ("call_1", "calculator", '{"operation":"add","a":1,"b":1}')
            ),
            make_tool_response(
                ("call_2", "calculator", '{"operation":"add","a":1,"b":1}')
            ),
        ],
        max_steps=2,
    )

    with pytest.raises(AgentMaxStepsExceededError, match="max_steps=2"):
        runtime.run(
            [ChatMessage(role="user", content="Keep calculating")],
            task_id=uuid4(),
        )


def test_runtime_max_steps_one_executes_tool_without_second_llm_call() -> None:
    executed_inputs: list[object] = []

    class RecordingCalculatorTool(CalculatorTool):
        def _execute(self, input_data):
            executed_inputs.append(input_data)
            return super()._execute(input_data)

    payloads: list[dict[str, object]] = []
    runtime = make_runtime(
        [
            make_tool_response(
                ("call_1", "calculator", '{"operation":"add","a":1,"b":2}')
            )
        ],
        payloads,
        max_steps=1,
        calculator=RecordingCalculatorTool(),
    )

    with pytest.raises(AgentMaxStepsExceededError, match="max_steps=1"):
        runtime.run(
            [ChatMessage(role="user", content="Keep calculating")],
            task_id=uuid4(),
        )

    assert len(payloads) == 1
    assert len(executed_inputs) == 1


@pytest.mark.parametrize(
    ("name", "arguments", "error_type", "error_match"),
    [
        ("missing", '{"operation":"add","a":1,"b":2}', ToolNotFoundError, "missing"),
        (
            "calculator",
            '{"operation":"invalid","a":1,"b":2}',
            ToolInputValidationError,
            "Invalid input",
        ),
        (
            "calculator",
            '{"operation":"divide","a":1,"b":0}',
            ToolExecutionError,
            "divide by zero",
        ),
    ],
)
def test_runtime_propagates_tool_errors(
    name: str,
    arguments: str,
    error_type: type[RuntimeError],
    error_match: str,
) -> None:
    runtime = make_runtime(
        [make_tool_response(("call_1", name, arguments))]
    )

    with pytest.raises(error_type, match=error_match):
        runtime.run(
            [ChatMessage(role="user", content="Use a tool")],
            task_id=uuid4(),
        )


def test_runtime_propagates_provider_errors() -> None:
    runtime = make_runtime(
        [{"error": "unavailable"}],
        status_code=503,
        max_attempts=1,
    )

    with pytest.raises(LLMProviderError, match="HTTP 503"):
        runtime.run(
            [ChatMessage(role="user", content="Use the model")],
            task_id=uuid4(),
        )


@pytest.mark.parametrize("content", [None, "", "   ", "\n"])
def test_runtime_rejects_empty_final_response(content: str | None) -> None:
    runtime = make_runtime(
        [{"choices": [{"message": {"content": content}}]}]
    )

    with pytest.raises(InvalidLLMResponseError, match="content"):
        runtime.run(
            [ChatMessage(role="user", content="Use the model")],
            task_id=uuid4(),
        )


@pytest.mark.parametrize("max_steps", [1, 3, 20])
def test_runtime_accepts_final_answer_on_last_allowed_round(max_steps):
    payloads = []
    runtime = make_runtime(
        [make_tool_response(
            (f"call_{i}", "calculator", '{"operation":"add","a":1,"b":2}')
        ) for i in range(max_steps - 1)]
        + [{"choices": [{"message": {"content": "  Final answer\n"}}]}],
        payloads,
        max_steps=max_steps,
    )
    messages = [ChatMessage(role="user", content="Calculate")]
    result = runtime.run(messages, task_id=uuid4())
    assert result.model_dump() == {"content": "  Final answer\n"}
    assert len(payloads) == max_steps
    assert len(messages) == 1


@pytest.mark.parametrize("max_steps", [1, 20])
def test_runtime_exhaustion_executes_all_tools_in_order(max_steps):
    executed = []

    class RecordingCalculator(CalculatorTool):
        def _execute(self, input_data):
            executed.append(input_data.a)
            return super()._execute(input_data)

    payloads = []
    runtime = make_runtime([
        make_tool_response(*[
            (f"call_{i}_{j}", "calculator",
             json.dumps({"operation": "add", "a": 2 * i + j, "b": 1}))
            for j in range(2)
        ]) for i in range(max_steps)
    ], payloads, max_steps=max_steps, calculator=RecordingCalculator())
    with pytest.raises(AgentMaxStepsExceededError, match=f"max_steps={max_steps}"):
        runtime.run([ChatMessage(role="user", content="Loop")], task_id=uuid4())
    assert len(payloads) == max_steps
    assert executed == list(range(2 * max_steps))


def test_runtime_reuse_does_not_leak_history_or_step_budget():
    payloads = []
    runtime = make_runtime([
        {"choices": [{"message": {"content": "First"}}]},
        {"choices": [{"message": {"content": "Second"}}]},
    ], payloads, max_steps=1)
    for prompt in ("First", "Second"):
        assert runtime.run(
            [ChatMessage(role="user", content=prompt)], task_id=uuid4()
        ).content == prompt
    assert [p["messages"] for p in payloads] == [
        [{"role": "user", "content": "First"}],
        [{"role": "user", "content": "Second"}],
    ]


def test_runtime_last_round_tool_failure_precedes_exhaustion():
    executed = []

    class RecordingCalculator(CalculatorTool):
        def _execute(self, input_data):
            executed.append(input_data.a)
            return super()._execute(input_data)

    runtime = make_runtime([make_tool_response(
        ("safe", "calculator", '{"operation":"add","a":1,"b":2}'),
        ("missing", "missing", '{}'),
        ("later", "calculator", '{"operation":"add","a":3,"b":4}'),
    )], max_steps=1, calculator=RecordingCalculator())
    with pytest.raises(ToolNotFoundError):
        runtime.run([ChatMessage(role="user", content="Tools")], task_id=uuid4())
    assert executed == [1]


def test_runtime_last_round_propagates_same_approval_signal():
    from unittest.mock import Mock

    from app.approvals.models import Approval
    from app.llm.schemas import LLMResponse, ToolCall
    from app.protected_execution import ApprovalRequired

    task_id = uuid4()
    call = ToolCall(id="protected", name="calculator", arguments={})
    signal = ApprovalRequired(Approval(
        task_id=task_id, tool_call_id=call.id,
        tool_name=call.name, arguments=call.arguments,
    ))
    llm = Mock()
    llm.chat.return_value = LLMResponse(tool_calls=[call, call])
    runtime = AgentRuntime(llm, make_registry(), max_steps=1)
    from unittest.mock import patch
    with patch("app.protected_execution.ProtectedToolExecutionService.execute",
               side_effect=signal) as execute:
        with pytest.raises(ApprovalRequired) as raised:
            runtime.run([ChatMessage(role="user", content="Protected")], task_id=task_id)
    assert raised.value is signal
    execute.assert_called_once_with(task_id=task_id, tool_call=call)
    llm.chat.assert_called_once()

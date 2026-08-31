import json

import httpx
import pytest

from app.core.config import Settings
from app.llm.client import InvalidLLMResponseError, LLMClient
from app.llm.schemas import ChatMessage, ToolCall
from app.tools.exceptions import (
    ToolExecutionError,
    ToolInputValidationError,
    ToolNotFoundError,
)
from app.tools.executor import ToolExecutor
from app.tools.implementations.calculator import CalculatorTool
from app.tools.registry import ToolRegistry


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="test-api-key",
        llm_base_url="https://llm.example.com/v1",
        llm_model="test-model",
    )


def make_tool_call_response(
    *,
    name: str = "calculator",
    arguments: str = '{"operation":"multiply","a":12,"b":8}',
) -> dict[str, object]:
    return {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_123",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": arguments,
                            },
                        }
                    ],
                }
            }
        ]
    }


def test_chat_sends_openai_compatible_tool_schema() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ready"}}]},
            request=request,
        )

    registry = ToolRegistry()
    registry.register(CalculatorTool())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)
        client.chat(
            [ChatMessage(role="user", content="Calculate 12 times 8")],
            tools=registry.list(),
        )

    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Perform one basic arithmetic operation on two numbers.",
                "parameters": CalculatorTool().metadata().input_schema,
            },
        }
    ]


def test_chat_parses_provider_tool_call_into_domain_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=make_tool_call_response(), request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)
        response = client.chat(
            [ChatMessage(role="user", content="Calculate 12 times 8")]
        )

    assert response.content is None
    assert response.tool_calls == [
        ToolCall(
            id="call_123",
            name="calculator",
            arguments={"operation": "multiply", "a": 12, "b": 8},
        )
    ]


def test_chat_rejects_invalid_tool_arguments_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_tool_call_response(arguments="{invalid-json"),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)

        with pytest.raises(InvalidLLMResponseError, match="invalid arguments JSON"):
            client.chat([ChatMessage(role="user", content="Calculate")])


def parse_tool_call(
    *,
    name: str = "calculator",
    arguments: str = '{"operation":"multiply","a":12,"b":8}',
) -> ToolCall:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=make_tool_call_response(name=name, arguments=arguments),
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)
        response = client.chat([ChatMessage(role="user", content="Calculate")])

    return response.tool_calls[0]


def make_executor() -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    return ToolExecutor(registry)


def test_tool_call_executes_calculator_end_to_end() -> None:
    result = make_executor().execute(parse_tool_call())

    assert result.tool_call_id == "call_123"
    assert result.tool_name == "calculator"
    assert result.content == "96.0"


def test_tool_call_unknown_tool_raises_domain_error() -> None:
    tool_call = parse_tool_call(name="missing")
    registry = ToolRegistry()

    with pytest.raises(ToolNotFoundError, match="Tool not found: missing"):
        ToolExecutor(registry).execute(tool_call)


def test_tool_call_invalid_input_uses_existing_validation_contract() -> None:
    tool_call = parse_tool_call(
        arguments='{"operation":"something","a":12,"b":8}'
    )

    with pytest.raises(ToolInputValidationError, match="Invalid input"):
        make_executor().execute(tool_call)


def test_tool_call_execution_error_is_propagated() -> None:
    tool_call = parse_tool_call(
        arguments='{"operation":"divide","a":12,"b":0}'
    )

    with pytest.raises(ToolExecutionError, match="divide by zero"):
        make_executor().execute(tool_call)

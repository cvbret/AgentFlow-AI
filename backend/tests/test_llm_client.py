import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.llm.client import (
    ConfigurationError,
    InvalidLLMResponseError,
    LLMClient,
    LLMProviderError,
)
from app.llm.schemas import ChatMessage


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        llm_api_key="test-api-key",
        llm_base_url="https://llm.example.com/v1/",
        llm_model="test-model",
    )


def test_settings_validates_and_exposes_llm_timeout() -> None:
    settings = Settings(
        _env_file=None,
        llm_api_key="test-api-key",
        llm_base_url="https://llm.example.com/v1/",
        llm_model="test-model",
        llm_timeout_seconds=12.5,
    )

    assert settings.llm_timeout_seconds == 12.5

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            llm_api_key="test-api-key",
            llm_base_url="https://llm.example.com/v1/",
            llm_model="test-model",
            llm_timeout_seconds=0,
        )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            llm_api_key="test-api-key",
            llm_base_url="https://llm.example.com/v1/",
            llm_model="test-model",
            llm_timeout_seconds=float("inf"),
        )


def test_settings_reads_llm_timeout_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-api-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example.com/v1/")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "4.25")

    settings = Settings(_env_file=None)

    assert settings.llm_timeout_seconds == 4.25


def test_chat_sends_openai_compatible_request_and_returns_content() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["json"] = request.read().decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello from the model"}}]},
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)
        result = client.chat(
            [
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="Hello"),
            ]
        )

    assert captured["url"] == "https://llm.example.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-api-key"
    assert captured["content_type"] == "application/json"
    assert captured["json"] == (
        '{"model":"test-model","messages":['
        '{"role":"system","content":"You are helpful."},'
        '{"role":"user","content":"Hello"}]}'
    )
    assert result.content == "Hello from the model"
    assert result.tool_calls == []


def test_chat_applies_explicit_timeout_to_http_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["timeout"] = request.extensions["timeout"]
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "Hello"}}]},
            request=request,
        )

    settings = Settings(
        _env_file=None,
        llm_api_key="test-api-key",
        llm_base_url="https://llm.example.com/v1",
        llm_model="test-model",
        llm_timeout_seconds=7.5,
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=settings, http_client=http_client)
        client.chat([ChatMessage(role="user", content="Hello")])

    assert captured["timeout"] == {
        "connect": 7.5,
        "read": 7.5,
        "write": 7.5,
        "pool": 7.5,
    }


def test_chat_raises_provider_error_for_non_2xx_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)

        with pytest.raises(LLMProviderError, match="HTTP 401"):
            client.chat([ChatMessage(role="user", content="Hello")])


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [
        (429, True),
        (500, True),
        (503, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
    ],
)
def test_chat_classifies_provider_http_failures(
    status_code: int,
    retryable: bool,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)

        with pytest.raises(LLMProviderError) as raised:
            client.chat([ChatMessage(role="user", content="Hello")])

    assert raised.value.retryable is retryable
    assert isinstance(raised.value.__cause__, httpx.HTTPStatusError)
    assert calls == 1


def test_chat_classifies_connection_failure_as_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)

        with pytest.raises(LLMProviderError, match="connection failed") as raised:
            client.chat([ChatMessage(role="user", content="Hello")])

    assert raised.value.retryable is True
    assert isinstance(raised.value.__cause__, httpx.ConnectError)


def test_chat_maps_http_timeout_to_provider_error() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        timeout = httpx.ReadTimeout("provider timed out", request=request)
        raise timeout

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)

        with pytest.raises(LLMProviderError, match="timed out") as raised:
            client.chat([ChatMessage(role="user", content="Hello")])

    assert isinstance(raised.value.__cause__, httpx.TimeoutException)
    assert raised.value.retryable is True
    assert calls == 1


def test_chat_raises_clear_error_for_invalid_response_structure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)

        with pytest.raises(
            InvalidLLMResponseError,
            match=r"choices\[0\]\.message\.content",
        ):
            client.chat([ChatMessage(role="user", content="Hello")])


def test_chat_message_rejects_invalid_role() -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role="tool", content="Not supported in TASK-002")


def test_client_raises_clear_error_when_configuration_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ConfigurationError, match="llm_api_key"):
        LLMClient()

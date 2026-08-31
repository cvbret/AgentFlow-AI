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


def test_chat_raises_provider_error_for_non_2xx_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"}, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings=make_settings(), http_client=http_client)

        with pytest.raises(LLMProviderError, match="HTTP 401"):
            client.chat([ChatMessage(role="user", content="Hello")])


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

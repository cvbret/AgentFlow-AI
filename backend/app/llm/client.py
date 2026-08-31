from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.llm.schemas import ChatMessage, LLMResponse


class LLMClientError(RuntimeError):
    """Base error for the LLM client boundary."""


class ConfigurationError(LLMClientError):
    """Raised when required LLM configuration is missing or invalid."""


class LLMProviderError(LLMClientError):
    """Raised when the provider request fails or returns a non-2xx status."""


class InvalidLLMResponseError(LLMClientError):
    """Raised when the provider response is not in the expected shape."""


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        try:
            self._settings = settings or get_settings()
        except ValidationError as exc:
            details = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise ConfigurationError(f"Invalid LLM configuration: {details}") from exc

        self._http_client = http_client or httpx.Client()

    @property
    def endpoint(self) -> str:
        return f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"

    def chat(self, messages: Sequence[ChatMessage]) -> LLMResponse:
        payload = {
            "model": self._settings.llm_model,
            "messages": [message.model_dump() for message in messages],
        }
        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._http_client.post(
                self.endpoint,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise LLMProviderError(
                f"LLM provider returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(f"LLM provider request failed: {exc}") from exc

        try:
            data: Any = response.json()
        except ValueError as exc:
            raise InvalidLLMResponseError(
                "LLM provider returned invalid JSON"
            ) from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidLLMResponseError(
                "LLM provider response is missing choices[0].message.content"
            ) from exc

        if not isinstance(content, str):
            raise InvalidLLMResponseError(
                "LLM provider response content must be a string"
            )

        return LLMResponse(content=content)

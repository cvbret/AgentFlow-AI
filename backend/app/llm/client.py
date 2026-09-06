import json
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.config import ConfigurationError, Settings, get_settings
from app.llm.schemas import ChatMessage, LLMResponse, ToolCall
from app.llm.tool_schema import OpenAICompatibleToolSchemaAdapter
from app.tools.schemas import ToolMetadata


class LLMClientError(RuntimeError):
    """Base error for the LLM client boundary."""


class LLMProviderError(LLMClientError):
    """Raised when the provider request fails or returns a non-2xx status."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class InvalidLLMResponseError(LLMClientError):
    """Raised when the provider response is not in the expected shape."""


class LLMClient:
    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._timeout = httpx.Timeout(self._settings.llm_timeout_seconds)

        self._owns_http_client = http_client is None
        self._http_client = (
            httpx.Client() if http_client is None else http_client
        )

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    @property
    def endpoint(self) -> str:
        return f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"

    def chat(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[ToolMetadata] | None = None,
    ) -> LLMResponse:
        payload = {
            "model": self._settings.llm_model,
            "messages": [self._serialize_message(message) for message in messages],
        }
        if tools is not None:
            payload["tools"] = OpenAICompatibleToolSchemaAdapter.convert_many(tools)

        headers = {
            "Authorization": f"Bearer {self._settings.llm_api_key}",
            "Content-Type": "application/json",
        }

        response = self._request_with_retry(headers=headers, payload=payload)

        try:
            data: Any = response.json()
        except ValueError as exc:
            raise InvalidLLMResponseError(
                "LLM provider returned invalid JSON"
            ) from exc

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InvalidLLMResponseError(
                "LLM provider response is missing choices[0].message.content "
                "or choices[0].message.tool_calls"
            ) from exc

        if not isinstance(message, dict):
            raise InvalidLLMResponseError(
                "LLM provider response message must be an object"
            )

        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise InvalidLLMResponseError(
                "LLM provider response content must be a string"
            )

        tool_calls = self._parse_tool_calls(message.get("tool_calls", []))
        if content is None and not tool_calls:
            raise InvalidLLMResponseError(
                "LLM provider response must contain content or tool_calls"
            )

        return LLMResponse(content=content, tool_calls=tool_calls)

    def _request_with_retry(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        for attempt in range(self._settings.llm_max_attempts):
            try:
                return self._request_once(headers=headers, payload=payload)
            except LLMProviderError as exc:
                if not exc.retryable or attempt + 1 >= self._settings.llm_max_attempts:
                    raise

        raise AssertionError("LLM retry loop exited without a response or error")

    def _request_once(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        try:
            response = self._http_client.post(
                self.endpoint,
                headers=headers,
                json=payload,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise LLMProviderError(
                "LLM provider request timed out",
                retryable=True,
            ) from exc
        except httpx.HTTPStatusError as exc:
            retryable = 500 <= exc.response.status_code < 600 or (
                exc.response.status_code == 429
            )
            raise LLMProviderError(
                f"LLM provider returned HTTP {exc.response.status_code}",
                retryable=retryable,
            ) from exc
        except httpx.NetworkError as exc:
            raise LLMProviderError(
                "LLM provider connection failed",
                retryable=True,
            ) from exc
        except httpx.RequestError as exc:
            raise LLMProviderError(
                f"LLM provider request failed: {exc}",
                retryable=False,
            ) from exc

        return response

    @staticmethod
    def _serialize_message(message: ChatMessage) -> dict[str, Any]:
        serialized: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
        }
        if message.role == "tool":
            serialized["tool_call_id"] = message.tool_call_id
        if message.role == "assistant" and message.tool_calls:
            serialized["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(
                            tool_call.arguments,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                }
                for tool_call in message.tool_calls
            ]
        return serialized

    @staticmethod
    def _parse_tool_calls(raw_tool_calls: Any) -> list[ToolCall]:
        if raw_tool_calls is None:
            return []
        if not isinstance(raw_tool_calls, list):
            raise InvalidLLMResponseError("LLM provider tool_calls must be a list")

        parsed_tool_calls: list[ToolCall] = []
        for index, raw_tool_call in enumerate(raw_tool_calls):
            try:
                call_id = raw_tool_call["id"]
                function = raw_tool_call["function"]
                name = function["name"]
                raw_arguments = function["arguments"]
            except (KeyError, TypeError) as exc:
                raise InvalidLLMResponseError(
                    f"LLM provider tool call at index {index} is invalid"
                ) from exc

            if not isinstance(call_id, str) or not isinstance(name, str):
                raise InvalidLLMResponseError(
                    f"LLM provider tool call at index {index} has invalid id or name"
                )

            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    raise InvalidLLMResponseError(
                        f"LLM provider tool call at index {index} has invalid arguments JSON"
                    ) from exc
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                raise InvalidLLMResponseError(
                    f"LLM provider tool call at index {index} arguments must be JSON"
                )

            if not isinstance(arguments, dict):
                raise InvalidLLMResponseError(
                    f"LLM provider tool call at index {index} arguments must be an object"
                )

            try:
                parsed_tool_calls.append(
                    ToolCall(id=call_id, name=name, arguments=arguments)
                )
            except ValidationError as exc:
                raise InvalidLLMResponseError(
                    f"LLM provider tool call at index {index} is invalid"
                ) from exc

        return parsed_tool_calls

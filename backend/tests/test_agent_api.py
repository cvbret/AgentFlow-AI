from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.agents.runtime import AgentMaxStepsExceededError, AgentResult
from app.api import dependencies
from app.api.dependencies import (
    get_agent_runtime_provider,
    get_task_execution_service,
)
from app.core.config import Settings, get_settings
from app.llm.client import (
    ConfigurationError,
    InvalidLLMResponseError,
    LLMClient,
    LLMProviderError,
)
from app.main import app
from app.llm.schemas import ChatMessage
from app.tasks.repository import TaskRepository
from app.tasks.service import TaskExecutionService
from app.tools.exceptions import ToolExecutionError, ToolNotFoundError


class FakeAgentRuntime:
    def __init__(self, result: AgentResult | None = None) -> None:
        self.messages: list[list[ChatMessage]] = []
        self.result = result or AgentResult(content="96")
        self.error: Exception | None = None

    def run(self, messages: list[ChatMessage]) -> AgentResult:
        self.messages.append(messages)
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        pass


class FakeTaskExecutionService:
    def __init__(self, runtime_provider: Callable[[], FakeAgentRuntime]) -> None:
        self._runtime_provider = runtime_provider

    def execute(self, message: str) -> SimpleNamespace:
        result = self._runtime_provider().run(
            [ChatMessage(role="user", content=message)]
        )
        return SimpleNamespace(result=result.content)


def override_task_execution_service(
    runtime_provider: Callable[[], FakeAgentRuntime] = Depends(
        get_agent_runtime_provider
    ),
) -> FakeTaskExecutionService:
    return FakeTaskExecutionService(runtime_provider)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_task_execution_service] = (
        override_task_execution_service
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_agent_run_returns_final_answer(
    client: TestClient,
) -> None:
    runtime = FakeAgentRuntime()
    app.dependency_overrides[get_agent_runtime_provider] = lambda: (
        lambda: runtime
    )

    response = client.post(
        "/api/agent/run",
        json={"message": "计算 12 × 8"},
    )

    assert response.status_code == 200
    assert response.json() == {"answer": "96"}
    assert runtime.messages == [
        [ChatMessage(role="user", content="计算 12 × 8")]
    ]


@pytest.mark.parametrize(
    "payload",
    [{"message": ""}, {"message": "  \n\t"}, {"message": None}, {}],
)
def test_agent_run_rejects_missing_or_blank_message(
    client: TestClient,
    payload: dict[str, object],
) -> None:
    response = client.post("/api/agent/run", json=payload)

    assert response.status_code == 422


def test_agent_run_maps_max_steps_error_safely(
    client: TestClient,
) -> None:
    runtime = FakeAgentRuntime()
    runtime.error = AgentMaxStepsExceededError("internal step details")
    app.dependency_overrides[get_agent_runtime_provider] = lambda: (
        lambda: runtime
    )

    response = client.post("/api/agent/run", json={"message": "继续执行"})

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Agent execution exceeded the maximum step limit."
    }
    assert "internal step details" not in response.text


@pytest.mark.parametrize(
    ("error", "status_code", "safe_detail", "sensitive_fragment"),
    [
        (
            LLMProviderError("provider secret and raw payload"),
            502,
            "LLM provider request failed.",
            "provider secret",
        ),
        (
            ConfigurationError("LLM_API_KEY=super-secret"),
            500,
            "Agent configuration is unavailable.",
            "super-secret",
        ),
        (
            InvalidLLMResponseError("raw provider payload at C:\\internal\\response"),
            502,
            "LLM provider returned an invalid response.",
            "raw provider payload",
        ),
        (
            ToolExecutionError("internal tool traceback at C:\\internal\\tool"),
            500,
            "Agent tool execution failed.",
            "internal tool traceback",
        ),
        (
            ToolNotFoundError("Tool not found: secret_tool"),
            500,
            "Agent tool execution failed.",
            "secret_tool",
        ),
    ],
)
def test_agent_run_maps_provider_and_configuration_errors_safely(
    client: TestClient,
    error: Exception,
    status_code: int,
    safe_detail: str,
    sensitive_fragment: str,
) -> None:
    runtime = FakeAgentRuntime()
    runtime.error = error
    app.dependency_overrides[get_agent_runtime_provider] = lambda: (
        lambda: runtime
    )

    response = client.post("/api/agent/run", json={"message": "调用模型"})

    assert response.status_code == status_code
    assert response.json() == {"detail": safe_detail}
    assert sensitive_fragment not in response.text
    assert "traceback" not in response.text.lower()
    assert "C:\\internal" not in response.text


def test_agent_run_keeps_provider_mapping_when_failed_persistence_fails(
    client: TestClient,
) -> None:
    runtime = FakeAgentRuntime()
    agent_error = LLMProviderError("provider secret and raw payload")
    runtime.error = agent_error
    repository = Mock(spec=TaskRepository)
    repository.save.side_effect = [
        None,
        None,
        SQLAlchemyError("failed state save failed"),
    ]
    service = TaskExecutionService(repository, lambda: runtime)
    app.dependency_overrides[get_task_execution_service] = lambda: service

    response = client.post(
        "/api/agent/run",
        json={"message": "调用模型"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "LLM provider request failed."}
    assert repository.save.call_count == 3
    assert "failed state save failed" not in response.text


def test_agent_run_maps_real_configuration_failure_safely(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides.clear()
    dependencies.close_agent_runtime()
    get_settings.cache_clear()
    for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)

    try:
        response = client.post(
            "/api/agent/run",
            json={"message": "调用模型"},
        )
    finally:
        dependencies.close_agent_runtime()
        get_settings.cache_clear()

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Agent configuration is unavailable."
    }
    assert "ValidationError" not in response.text
    assert "traceback" not in response.text.lower()
    assert "LLM_API_KEY" not in response.text
    assert "E:\\AIProjects\\AgentFlow-AI" not in response.text


def test_runtime_initialization_is_thread_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies.close_agent_runtime()
    runtime = FakeAgentRuntime()
    build_count = 0
    build_started = Event()
    release_build = Event()

    def build_runtime() -> FakeAgentRuntime:
        nonlocal build_count
        build_count += 1
        build_started.set()
        assert release_build.wait(timeout=2)
        return runtime

    monkeypatch.setattr(dependencies, "build_agent_runtime", build_runtime)

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(dependencies.get_agent_runtime)
                for _ in range(32)
            ]
            assert build_started.wait(timeout=2)
            release_build.set()
            runtimes = [future.result() for future in futures]
    finally:
        dependencies.close_agent_runtime()

    assert build_count == 1
    assert all(candidate is runtime for candidate in runtimes)


def test_runtime_initialization_failure_is_not_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependencies.close_agent_runtime()
    attempts = 0

    def build_runtime() -> FakeAgentRuntime:
        nonlocal attempts
        attempts += 1
        raise ConfigurationError("missing configuration")

    monkeypatch.setattr(dependencies, "build_agent_runtime", build_runtime)

    with pytest.raises(ConfigurationError):
        dependencies.get_agent_runtime()
    with pytest.raises(ConfigurationError):
        dependencies.get_agent_runtime()

    assert attempts == 2
    assert dependencies._agent_runtime is None


def test_llm_client_closes_client_it_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RecordingClient:
        closed = False

        def close(self) -> None:
            self.closed = True

    internal_client = RecordingClient()
    monkeypatch.setattr(httpx, "Client", lambda: internal_client)

    client = LLMClient(
        settings=Settings(
            _env_file=None,
            llm_api_key="test-key",
            llm_base_url="https://llm.example.com",
            llm_model="test-model",
        )
    )
    client.close()

    assert internal_client.closed


def test_llm_client_does_not_close_external_client() -> None:
    external_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, request=request)
        )
    )
    client = LLMClient(
        settings=Settings(
            _env_file=None,
            llm_api_key="test-key",
            llm_base_url="https://llm.example.com",
            llm_model="test-model",
        ),
        http_client=external_client,
    )

    client.close()

    assert not external_client.is_closed
    external_client.close()


def test_health_endpoint_still_returns_ok(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

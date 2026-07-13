"""Offline tests for the OpenAI-compatible LLM HTTP client."""

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

import httpx
import pytest

import app.llm.client as llm_client_module
from app.llm import (
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponse,
    LLMResponseError,
    OpenAICompatibleLLMClient,
)


ENVIRONMENT_VARIABLES = (
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_TIMEOUT_SECONDS",
    "LLM_TEMPERATURE",
)
TEST_API_KEY = "unit-test-key"
MESSAGES = [{"role": "user", "content": "Hello"}]
VALID_RESPONSE: Dict[str, Any] = {
    "id": "chatcmpl-test",
    "model": "response-model",
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": "Hello from the model",
            }
        }
    ],
    "usage": {
        "prompt_tokens": 1,
        "completion_tokens": 4,
        "total_tokens": 5,
    },
}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent a developer's real .env from affecting test outcomes."""
    for variable_name in ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable_name, raising=False)
    monkeypatch.setattr(llm_client_module, "load_dotenv", lambda **kwargs: False)


@pytest.fixture
def config() -> LLMConfig:
    """Return safe configuration containing no real credential."""
    return LLMConfig(
        api_key=TEST_API_KEY,
        base_url="https://llm.example/v1",
        model="request-model",
    )


@pytest.fixture
def validation_client(
    config: LLMConfig,
) -> Iterator[OpenAICompatibleLLMClient]:
    """Provide a client whose transport fails if validation reaches the network."""

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        pytest.fail("Message validation unexpectedly sent an HTTP request.")

    with httpx.Client(transport=httpx.MockTransport(unexpected_request)) as http_client:
        yield OpenAICompatibleLLMClient(config, http_client=http_client)


def set_valid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Populate the minimum valid LLM environment for a test."""
    monkeypatch.setenv("LLM_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def run_json_response(response_data: Any, config: LLMConfig) -> LLMResponse:
    """Run one completion against an in-memory JSON response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_data)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)
        return client.complete(MESSAGES)


def test_config_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)

    config = LLMConfig.from_env()

    assert config.api_key == TEST_API_KEY
    assert config.base_url == "https://llm.example/v1"
    assert config.model == "test-model"


def test_config_loads_project_root_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)
    captured: Dict[str, Any] = {}

    def fake_load_dotenv(**kwargs: Any) -> bool:
        captured.update(kwargs)
        return True

    monkeypatch.setattr(llm_client_module, "load_dotenv", fake_load_dotenv)

    LLMConfig.from_env()

    dotenv_path = Path(captured["dotenv_path"])
    assert dotenv_path.name == ".env"
    assert dotenv_path.parent == Path(llm_client_module.__file__).resolve().parents[2]
    assert captured["override"] is False


@pytest.mark.parametrize(
    ("missing_variable", "expected_name"),
    [
        ("LLM_API_KEY", "LLM_API_KEY"),
        ("LLM_BASE_URL", "LLM_BASE_URL"),
        ("LLM_MODEL", "LLM_MODEL"),
    ],
)
def test_config_rejects_missing_required_value(
    monkeypatch: pytest.MonkeyPatch,
    missing_variable: str,
    expected_name: str,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.delenv(missing_variable)

    with pytest.raises(LLMConfigurationError, match=expected_name):
        LLMConfig.from_env()


@pytest.mark.parametrize("variable_name", ["LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"])
def test_config_rejects_blank_required_value(
    monkeypatch: pytest.MonkeyPatch,
    variable_name: str,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv(variable_name, "   ")

    with pytest.raises(LLMConfigurationError, match=variable_name):
        LLMConfig.from_env()


def test_config_uses_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)

    assert LLMConfig.from_env().timeout_seconds == 60.0


def test_config_uses_default_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)

    assert LLMConfig.from_env().temperature == 0.0


def test_config_reads_custom_numbers(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("LLM_TEMPERATURE", "0.25")

    config = LLMConfig.from_env()

    assert config.timeout_seconds == 12.5
    assert config.temperature == 0.25


def test_config_rejects_non_numeric_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "slow")

    with pytest.raises(LLMConfigurationError, match="LLM_TIMEOUT_SECONDS"):
        LLMConfig.from_env()


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_config_rejects_non_positive_timeout(
    monkeypatch: pytest.MonkeyPatch,
    timeout: str,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", timeout)

    with pytest.raises(LLMConfigurationError, match="greater than 0"):
        LLMConfig.from_env()


def test_config_rejects_non_numeric_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_environment(monkeypatch)
    monkeypatch.setenv("LLM_TEMPERATURE", "warm")

    with pytest.raises(LLMConfigurationError, match="LLM_TEMPERATURE"):
        LLMConfig.from_env()


def test_config_appends_chat_completions_path() -> None:
    config = LLMConfig(TEST_API_KEY, "https://llm.example/v1", "model")

    assert config.chat_completions_url == "https://llm.example/v1/chat/completions"


def test_config_does_not_duplicate_chat_completions_path() -> None:
    config = LLMConfig(
        TEST_API_KEY,
        "https://llm.example/v1/chat/completions",
        "model",
    )

    assert config.chat_completions_url == "https://llm.example/v1/chat/completions"


def test_config_removes_trailing_slashes() -> None:
    config = LLMConfig(TEST_API_KEY, "https://llm.example/v1///", "model")

    assert config.base_url == "https://llm.example/v1"
    assert config.chat_completions_url == "https://llm.example/v1/chat/completions"


def test_messages_must_not_be_empty(
    validation_client: OpenAICompatibleLLMClient,
) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validation_client.complete([])


def test_messages_must_be_a_list(
    validation_client: OpenAICompatibleLLMClient,
) -> None:
    with pytest.raises(ValueError, match="must be a list"):
        validation_client.complete("message")  # type: ignore[arg-type]


def test_message_must_be_an_object(
    validation_client: OpenAICompatibleLLMClient,
) -> None:
    with pytest.raises(ValueError, match="must be an object"):
        validation_client.complete(["message"])  # type: ignore[list-item]


def test_message_requires_role(validation_client: OpenAICompatibleLLMClient) -> None:
    with pytest.raises(ValueError, match="missing 'role'"):
        validation_client.complete([{"content": "Hello"}])


def test_message_requires_content(
    validation_client: OpenAICompatibleLLMClient,
) -> None:
    with pytest.raises(ValueError, match="missing 'content'"):
        validation_client.complete([{"role": "user"}])


def test_message_rejects_invalid_role(
    validation_client: OpenAICompatibleLLMClient,
) -> None:
    with pytest.raises(ValueError, match="role"):
        validation_client.complete([{"role": "tool", "content": "Hello"}])


def test_message_content_must_be_a_string(
    validation_client: OpenAICompatibleLLMClient,
) -> None:
    with pytest.raises(ValueError, match="must be a string"):
        validation_client.complete(  # type: ignore[arg-type]
            [{"role": "user", "content": 123}]
        )


@pytest.mark.parametrize("content", ["", "   "])
def test_message_content_must_not_be_blank(
    validation_client: OpenAICompatibleLLMClient,
    content: str,
) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validation_client.complete([{"role": "user", "content": content}])


def test_complete_parses_standard_response(config: LLMConfig) -> None:
    result = run_json_response(VALID_RESPONSE, config)

    assert result.content == "Hello from the model"
    assert result.model == "response-model"
    assert result.usage == VALID_RESPONSE["usage"]
    assert result.raw_response == VALID_RESPONSE
    assert result.to_dict()["content"] == "Hello from the model"


def test_complete_sends_expected_request(config: LLMConfig) -> None:
    captured: Dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers["Content-Type"]
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=VALID_RESPONSE)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)
        client.complete(MESSAGES)

    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer {}".format(TEST_API_KEY)
    assert captured["content_type"] == "application/json"
    assert captured["body"] == {
        "model": "request-model",
        "messages": MESSAGES,
        "temperature": 0.0,
    }


@pytest.mark.parametrize("status_code", [401, 500])
def test_http_error_becomes_request_error(
    config: LLMConfig,
    status_code: int,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="response body must stay private")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)
        with pytest.raises(LLMRequestError, match=str(status_code)) as error_info:
            client.complete(MESSAGES)

    assert "response body must stay private" not in str(error_info.value)


def test_timeout_becomes_request_error(config: LLMConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout details", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)
        with pytest.raises(LLMRequestError, match="timed out"):
            client.complete(MESSAGES)


def test_network_error_becomes_request_error(config: LLMConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection details", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)
        with pytest.raises(LLMRequestError, match="network"):
            client.complete(MESSAGES)


def test_non_json_response_becomes_response_error(config: LLMConfig) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)
        with pytest.raises(LLMResponseError, match="valid JSON") as error_info:
            client.complete(MESSAGES)

    assert "not-json" not in str(error_info.value)


@pytest.mark.parametrize(
    ("response_data", "expected_error"),
    [
        ([], "JSON object"),
        ({}, "missing 'choices'"),
        ({"choices": "invalid"}, "must be a list"),
        ({"choices": []}, "must not be empty"),
        ({"choices": ["invalid"]}, "choice must be an object"),
        ({"choices": [{}]}, "missing 'message'"),
        ({"choices": [{"message": "invalid"}]}, "message.*object"),
        ({"choices": [{"message": {}}]}, "missing 'content'"),
        ({"choices": [{"message": {"content": 42}}]}, "content.*string"),
        ({"choices": [{"message": {"content": "   "}}]}, "content.*empty"),
        (
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": "invalid",
            },
            "usage.*object",
        ),
        (
            {
                "choices": [{"message": {"content": "ok"}}],
                "model": 42,
            },
            "model.*string",
        ),
    ],
)
def test_invalid_response_structure_is_rejected(
    config: LLMConfig,
    response_data: Any,
    expected_error: str,
) -> None:
    with pytest.raises(LLMResponseError, match=expected_error):
        run_json_response(response_data, config)


def test_request_error_does_not_expose_api_key() -> None:
    secret = "credential-that-must-not-appear"
    config = LLMConfig(secret, "https://llm.example/v1", "model")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(secret, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)
        with pytest.raises(LLMRequestError) as error_info:
            client.complete(MESSAGES)

    assert secret not in str(error_info.value)


def test_close_closes_owned_http_client(config: LLMConfig) -> None:
    client = OpenAICompatibleLLMClient(config)
    owned_http_client = client._http_client

    client.close()

    assert owned_http_client.is_closed is True


def test_close_does_not_close_injected_http_client(config: LLMConfig) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda request: None)) as http_client:
        client = OpenAICompatibleLLMClient(config, http_client=http_client)

        client.close()

        assert http_client.is_closed is False


def test_context_manager_closes_owned_http_client(config: LLMConfig) -> None:
    with OpenAICompatibleLLMClient(config) as client:
        owned_http_client = client._http_client
        assert owned_http_client.is_closed is False

    assert owned_http_client.is_closed is True

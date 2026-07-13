"""Offline tests for the manual LLM smoke-test script."""

import json
from typing import Dict, List, Optional

import pytest

import scripts.llm_smoke_test as smoke_module
from app.agent import AgentDecision, AgentOutputParseError, ParsedToolCall
from app.llm import (
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponse,
    LLMResponseError,
)
from app.tools import create_default_registry
from scripts.llm_smoke_test import (
    DEFAULT_SMOKE_PROMPT,
    build_smoke_messages,
    run_smoke_test,
    validate_smoke_decision,
)


def calculator_response_content(expression: object = "12 * (3 + 2)") -> str:
    """Return a model response that selects calculator."""
    return json.dumps(
        {
            "type": "tool_call",
            "reasoning_summary": "需要调用计算器。",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "calculator",
                    "arguments": {"expression": expression},
                }
            ],
        },
        ensure_ascii=False,
    )


def calculator_decision(expression: object = "12 * (3 + 2)") -> AgentDecision:
    """Build a decision directly for validation tests."""
    return AgentDecision(
        type="tool_call",
        reasoning_summary="需要调用计算器。",
        tool_calls=[
            ParsedToolCall(
                id="call_1",
                name="calculator",
                arguments={"expression": expression},
            )
        ],
    )


class FakeLLMClient:
    """Minimal injected client used without any network transport."""

    def __init__(
        self,
        response: Optional[LLMResponse] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.response = response or LLMResponse(
            content=calculator_response_content(),
            model="fake-model",
        )
        self.error = error
        self.received_messages: Optional[List[Dict[str, str]]] = None
        self.closed = False

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        self.received_messages = messages
        if self.error is not None:
            raise self.error
        return self.response

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def config() -> LLMConfig:
    """Return placeholder-only configuration for offline tests."""
    return LLMConfig(
        api_key="unit-test-placeholder",
        base_url="https://llm.invalid/v1",
        model="test-model",
    )


@pytest.fixture
def smoke_messages() -> List[Dict[str, str]]:
    """Build the default smoke-test messages."""
    schemas = create_default_registry().get_tool_schemas()
    return build_smoke_messages(schemas)


def test_build_messages_returns_system_and_user(smoke_messages: List[Dict[str, str]]) -> None:
    assert [message["role"] for message in smoke_messages] == ["system", "user"]
    assert len(smoke_messages) == 2


@pytest.mark.parametrize("tool_name", ["calculator", "search", "todo"])
def test_system_message_contains_default_tools(
    smoke_messages: List[Dict[str, str]],
    tool_name: str,
) -> None:
    assert '"name": "{}"'.format(tool_name) in smoke_messages[0]["content"]


def test_user_message_contains_default_request(
    smoke_messages: List[Dict[str, str]],
) -> None:
    assert DEFAULT_SMOKE_PROMPT in smoke_messages[1]["content"]


def test_build_messages_supports_custom_user_prompt() -> None:
    schemas = create_default_registry().get_tool_schemas()

    messages = build_smoke_messages(schemas, "请计算 2 + 2")

    assert messages[1] == {"role": "user", "content": "请计算 2 + 2"}


def test_valid_calculator_decision_passes() -> None:
    validate_smoke_decision(calculator_decision())


def test_calculator_decision_contains_expression() -> None:
    decision = calculator_decision()

    validate_smoke_decision(decision)

    assert "expression" in decision.tool_calls[0].arguments


def test_final_decision_fails_validation() -> None:
    decision = AgentDecision(
        type="final",
        reasoning_summary="直接回答。",
        answer="60",
    )

    with pytest.raises(ValueError, match="final"):
        validate_smoke_decision(decision)


def test_wrong_tool_fails_validation() -> None:
    decision = AgentDecision(
        type="tool_call",
        reasoning_summary="选择搜索。",
        tool_calls=[ParsedToolCall("call_1", "search", {"query": "calculation"})],
    )

    with pytest.raises(ValueError, match="calculator"):
        validate_smoke_decision(decision)


def test_empty_tool_calls_fail_validation() -> None:
    decision = calculator_decision()
    decision.tool_calls.clear()

    with pytest.raises(ValueError, match="without any tool calls"):
        validate_smoke_decision(decision)


def test_calculator_without_expression_fails_validation() -> None:
    decision = AgentDecision(
        type="tool_call",
        reasoning_summary="选择计算器。",
        tool_calls=[ParsedToolCall("call_1", "calculator", {})],
    )

    with pytest.raises(ValueError, match="expression.*string"):
        validate_smoke_decision(decision)


def test_non_string_expression_fails_validation() -> None:
    with pytest.raises(ValueError, match="expression.*string"):
        validate_smoke_decision(calculator_decision(60))


@pytest.mark.parametrize("expression", ["", "   "])
def test_blank_expression_fails_validation(expression: str) -> None:
    with pytest.raises(ValueError, match="expression.*empty"):
        validate_smoke_decision(calculator_decision(expression))


def test_run_smoke_test_calls_injected_client() -> None:
    fake_client = FakeLLMClient()

    run_smoke_test(llm_client=fake_client)  # type: ignore[arg-type]

    assert fake_client.received_messages is not None
    assert fake_client.received_messages[1]["content"] == DEFAULT_SMOKE_PROMPT


def test_run_smoke_test_parses_model_response() -> None:
    fake_client = FakeLLMClient()

    decision = run_smoke_test(llm_client=fake_client)  # type: ignore[arg-type]

    assert decision.type == "tool_call"
    assert decision.tool_calls[0].name == "calculator"


def test_run_smoke_test_returns_agent_decision() -> None:
    fake_client = FakeLLMClient()

    result = run_smoke_test(llm_client=fake_client)  # type: ignore[arg-type]

    assert isinstance(result, AgentDecision)


def test_injected_client_is_not_closed() -> None:
    fake_client = FakeLLMClient()

    run_smoke_test(llm_client=fake_client)  # type: ignore[arg-type]

    assert fake_client.closed is False


def test_internally_created_client_is_closed(
    monkeypatch: pytest.MonkeyPatch,
    config: LLMConfig,
) -> None:
    fake_client = FakeLLMClient()
    monkeypatch.setattr(
        smoke_module,
        "OpenAICompatibleLLMClient",
        lambda supplied_config: fake_client,
    )

    run_smoke_test(config=config)

    assert fake_client.closed is True


@pytest.mark.parametrize(
    ("error", "expected_message"),
    [
        (LLMConfigurationError("private details"), "configuration"),
        (LLMRequestError("private details"), "request failed"),
        (LLMResponseError("private details"), "invalid response"),
        (AgentOutputParseError("private details"), "JSON protocol"),
    ],
)
def test_main_catches_expected_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
    expected_message: str,
) -> None:
    def raise_error() -> AgentDecision:
        raise error

    monkeypatch.setattr(smoke_module, "run_smoke_test", raise_error)

    exit_code = smoke_module.main()

    captured = capsys.readouterr()
    assert exit_code != 0
    assert expected_message in captured.err
    assert "private details" not in captured.err


def test_main_returns_nonzero_for_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_validation_error() -> AgentDecision:
        raise ValueError("LLM did not select the calculator tool.")

    monkeypatch.setattr(smoke_module, "run_smoke_test", raise_validation_error)

    assert smoke_module.main() != 0


def test_main_returns_zero_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smoke_module, "run_smoke_test", calculator_decision)

    assert smoke_module.main() == 0


def test_error_output_does_not_include_api_key(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "api-key-that-must-not-appear"

    def raise_request_error() -> AgentDecision:
        raise LLMRequestError(secret)

    monkeypatch.setattr(smoke_module, "run_smoke_test", raise_request_error)

    smoke_module.main()

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_success_output_redacts_configured_api_key(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "configured-secret-value"
    config = LLMConfig(secret, "https://llm.invalid/v1", "test-model")
    fake_client = FakeLLMClient(
        response=LLMResponse(
            content=calculator_response_content(secret),
            model="fake-model",
        )
    )

    run_smoke_test(
        config=config,
        llm_client=fake_client,  # type: ignore[arg-type]
    )

    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err

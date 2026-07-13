"""Manual real-API smoke test for structured LLM tool selection."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

from app.agent import (
    AgentDecision,
    AgentOutputParseError,
    build_agent_system_prompt,
    parse_llm_output,
)
from app.llm import (
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponse,
    LLMResponseError,
    OpenAICompatibleLLMClient,
)
from app.tools import create_default_registry


DEFAULT_SMOKE_PROMPT = "请帮我计算 12 * (3 + 2)"


class SmokeTestValidationError(ValueError):
    """Raised when the model does not select calculator as required."""


def build_smoke_messages(
    tool_schemas: List[Dict[str, Any]],
    user_prompt: str = DEFAULT_SMOKE_PROMPT,
) -> List[Dict[str, str]]:
    """Build the system and user messages used by the smoke test."""
    if not isinstance(user_prompt, str) or not user_prompt.strip():
        raise ValueError("user_prompt must be a non-empty string.")
    system_prompt = build_agent_system_prompt(tool_schemas)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt.strip()},
    ]


def validate_smoke_decision(decision: AgentDecision) -> None:
    """Verify that the model selected calculator with an expression argument."""
    if not isinstance(decision, AgentDecision):
        raise SmokeTestValidationError("Smoke test did not return an AgentDecision.")
    if decision.type == "final":
        raise SmokeTestValidationError(
            "LLM returned final instead of selecting calculator."
        )
    if decision.type != "tool_call":
        raise SmokeTestValidationError("LLM returned an unsupported decision type.")
    if not decision.tool_calls:
        raise SmokeTestValidationError(
            "LLM returned tool_call without any tool calls."
        )

    calculator_call = next(
        (tool_call for tool_call in decision.tool_calls if tool_call.name == "calculator"),
        None,
    )
    if calculator_call is None:
        raise SmokeTestValidationError("LLM did not select the calculator tool.")

    expression = calculator_call.arguments.get("expression")
    if not isinstance(expression, str):
        raise SmokeTestValidationError(
            "Calculator argument 'expression' must be a string."
        )
    if not expression.strip():
        raise SmokeTestValidationError(
            "Calculator argument 'expression' must not be empty."
        )


def run_smoke_test(
    config: Optional[LLMConfig] = None,
    llm_client: Optional[OpenAICompatibleLLMClient] = None,
    user_prompt: str = DEFAULT_SMOKE_PROMPT,
) -> AgentDecision:
    """Call the LLM, parse its decision, and verify calculator selection."""
    registry = create_default_registry()
    messages = build_smoke_messages(registry.get_tool_schemas(), user_prompt)

    active_config = config
    owns_client = llm_client is None
    if llm_client is None:
        active_config = active_config or LLMConfig.from_env()
        active_client = OpenAICompatibleLLMClient(active_config)
    else:
        active_client = llm_client
        if active_config is None:
            injected_config = getattr(active_client, "config", None)
            if isinstance(injected_config, LLMConfig):
                active_config = injected_config

    try:
        response = active_client.complete(messages)
        decision = parse_llm_output(response.content)
        validate_smoke_decision(decision)
        _print_success(response, decision, active_config)
        return decision
    finally:
        if owns_client:
            active_client.close()


def main() -> int:
    """Run the smoke test and translate expected failures to a process status."""
    try:
        run_smoke_test()
    except LLMConfigurationError:
        _print_failure("LLM configuration is missing or invalid.")
        return 1
    except LLMRequestError:
        _print_failure("The LLM request failed.")
        return 1
    except LLMResponseError:
        _print_failure("The LLM API returned an invalid response.")
        return 1
    except AgentOutputParseError:
        _print_failure("The model output did not match the required JSON protocol.")
        return 1
    except SmokeTestValidationError as error:
        _print_failure(str(error))
        return 1
    except ValueError:
        _print_failure("Smoke-test input or decision validation failed.")
        return 1
    return 0


def _print_success(
    response: LLMResponse,
    decision: AgentDecision,
    config: Optional[LLMConfig],
) -> None:
    secrets = [config.api_key] if config is not None else []
    model_name = response.model or (config.model if config is not None else "unknown")
    raw_content = _redact(response.content, secrets)
    parsed_content = _redact(
        json.dumps(decision.to_dict(), ensure_ascii=False, indent=2),
        secrets,
    )

    print("=== Minimal Agent LLM Smoke Test ===")
    print("Model: {}".format(_redact(model_name, secrets)))
    print()
    print("Raw LLM content:")
    print(raw_content)
    print()
    print("Parsed decision:")
    print(parsed_content)
    print()
    print("Smoke test passed: LLM selected calculator.")


def _print_failure(message: str) -> None:
    print("Smoke test failed: {}".format(message), file=sys.stderr)


def _redact(value: str, secrets: List[str]) -> str:
    redacted_value = value
    for secret in secrets:
        if secret:
            redacted_value = redacted_value.replace(secret, "[REDACTED]")
    return redacted_value


if __name__ == "__main__":
    raise SystemExit(main())

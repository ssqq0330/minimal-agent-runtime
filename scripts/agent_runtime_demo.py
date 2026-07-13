"""Manual real-API demonstration of the core Agent Runtime loop."""

from __future__ import annotations

import json
import sys
from typing import Optional

from app.agent import AgentRunResult, AgentRuntime, AgentRuntimeError
from app.llm import LLMConfig, LLMConfigurationError, OpenAICompatibleLLMClient
from app.tools import ToolContext, create_default_registry


DEMO_USER_INPUT = "请帮我计算 12 * (3 + 2)，并告诉我结果。"


def main() -> int:
    """Run a real Agent loop and print its final answer and step summaries."""
    client: Optional[OpenAICompatibleLLMClient] = None
    try:
        config = LLMConfig.from_env()
        client = OpenAICompatibleLLMClient(config)
        runtime = AgentRuntime(
            llm_client=client,
            tool_registry=create_default_registry(),
            max_steps=5,
        )
        result = runtime.run(
            user_input=DEMO_USER_INPUT,
            context=ToolContext(
                user_id="demo-user",
                session_id="demo-session",
            ),
        )
        _print_result(result)
        return 0
    except LLMConfigurationError:
        _print_failure("LLM configuration is missing or invalid.")
        return 1
    except AgentRuntimeError as error:
        _print_failure(str(error))
        return 1
    finally:
        if client is not None:
            client.close()


def _print_result(run_result: AgentRunResult) -> None:
    print("=== Minimal Agent Runtime Demo ===")
    print("Final answer: {}".format(run_result.answer))
    print("LLM calls: {}".format(run_result.total_llm_calls))
    print("Tool calls: {}".format(run_result.total_tool_calls))
    print()
    for step in run_result.steps:
        print(
            "Step {} [{}]: {}".format(
                step.step_number,
                step.decision_type,
                step.reasoning_summary,
            )
        )
        for tool_result in step.tool_results:
            print(
                json.dumps(
                    {
                        "tool_name": tool_result["tool_name"],
                        "arguments": tool_result["arguments"],
                        "result": tool_result["result"],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )


def _print_failure(message: str) -> None:
    print("Agent Runtime demo failed: {}".format(message), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())

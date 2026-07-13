"""Offline tests for the self-managed Agent Runtime loop."""

import copy
import json
from typing import Dict, List, Optional, Union

import pytest

from app.agent import (
    AgentDecisionError,
    AgentInputError,
    AgentLLMError,
    AgentMaxStepsError,
    AgentRunResult,
    AgentRuntime,
    AgentStep,
)
from app.llm import (
    LLMConfig,
    LLMConfigurationError,
    LLMRequestError,
    LLMResponse,
    LLMResponseError,
)
from app.tools import ToolContext, ToolRegistry, create_default_registry


FakeResponse = Union[str, Exception]


def final_content(answer: str = "最终答案") -> str:
    return json.dumps(
        {
            "type": "final",
            "reasoning_summary": "已经可以直接回答。",
            "answer": answer,
        },
        ensure_ascii=False,
    )


def tool_call_content(tool_calls: List[Dict[str, object]]) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "reasoning_summary": "需要调用工具。",
            "tool_calls": tool_calls,
        },
        ensure_ascii=False,
    )


def calculator_call(
    expression: str = "12 * (3 + 2)",
    call_id: str = "call_1",
) -> Dict[str, object]:
    return {
        "id": call_id,
        "name": "calculator",
        "arguments": {"expression": expression},
    }


class FakeLLMClient:
    """Return predefined responses and record immutable message snapshots."""

    def __init__(
        self,
        responses: List[FakeResponse],
        config: Optional[LLMConfig] = None,
    ) -> None:
        self._responses = list(responses)
        self.config = config
        self.calls: List[List[Dict[str, str]]] = []
        self.closed = False

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])
        if not self._responses:
            raise RuntimeError("FakeLLMClient response list is exhausted.")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(content=response, model="fake-model")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def context() -> ToolContext:
    return ToolContext(user_id="user-1", session_id="session-1")


def make_runtime(
    responses: List[FakeResponse],
    max_steps: int = 8,
    registry: Optional[ToolRegistry] = None,
    config: Optional[LLMConfig] = None,
) -> tuple[AgentRuntime, FakeLLMClient, ToolRegistry]:
    fake_client = FakeLLMClient(responses, config=config)
    actual_registry = registry or create_default_registry()
    runtime = AgentRuntime(  # type: ignore[arg-type]
        llm_client=fake_client,
        tool_registry=actual_registry,
        max_steps=max_steps,
    )
    return runtime, fake_client, actual_registry


def run_calculator_loop(
    context: ToolContext,
    expression: str = "12 * (3 + 2)",
) -> tuple[AgentRunResult, FakeLLMClient]:
    runtime, fake_client, _ = make_runtime(
        [tool_call_content([calculator_call(expression)]), final_content("结果是 60。")]
    )
    return runtime.run("请计算", context), fake_client


def test_runtime_initializes_with_max_steps() -> None:
    runtime, _, _ = make_runtime([final_content()], max_steps=3)

    assert runtime.max_steps == 3


@pytest.mark.parametrize("max_steps", [0, -1])
def test_runtime_rejects_non_positive_max_steps(max_steps: int) -> None:
    with pytest.raises(ValueError, match="max_steps"):
        make_runtime([final_content()], max_steps=max_steps)


@pytest.mark.parametrize("max_steps", [1.5, "2", True])
def test_runtime_rejects_non_integer_max_steps(max_steps: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        make_runtime([final_content()], max_steps=max_steps)  # type: ignore[arg-type]


@pytest.mark.parametrize("user_input", ["", "   "])
def test_runtime_rejects_empty_user_input(
    context: ToolContext,
    user_input: str,
) -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match="must not be empty"):
        runtime.run(user_input, context)


def test_runtime_rejects_non_string_user_input(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match="must be a string"):
        runtime.run(123, context)  # type: ignore[arg-type]


def test_runtime_rejects_invalid_context() -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match="ToolContext"):
        runtime.run("hello", object())  # type: ignore[arg-type]


def test_runtime_rejects_non_list_history(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match="history must be a list"):
        runtime.run("hello", context, history={})  # type: ignore[arg-type]


def test_runtime_rejects_non_object_history_item(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match=r"history\[0\].*object"):
        runtime.run("hello", context, history=["invalid"])  # type: ignore[list-item]


def test_runtime_rejects_system_history(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match="system is not allowed"):
        runtime.run("hello", context, [{"role": "system", "content": "prompt"}])


def test_runtime_rejects_invalid_history_role(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match="user or assistant"):
        runtime.run("hello", context, [{"role": "tool", "content": "result"}])


@pytest.mark.parametrize("content", ["", "  "])
def test_runtime_rejects_empty_history_content(
    context: ToolContext,
    content: str,
) -> None:
    runtime, _, _ = make_runtime([final_content()])

    with pytest.raises(AgentInputError, match="content must not be empty"):
        runtime.run("hello", context, [{"role": "user", "content": content}])


def test_runtime_does_not_modify_original_history(context: ToolContext) -> None:
    history = [
        {"role": "user", "content": "Earlier question", "metadata": "keep"},
        {"role": "assistant", "content": "Earlier answer"},
    ]
    original_history = copy.deepcopy(history)
    runtime, _, _ = make_runtime([final_content()])

    runtime.run("new question", context, history)  # type: ignore[arg-type]

    assert history == original_history


def test_first_llm_decision_can_be_final(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content("Direct answer")])

    result = runtime.run("hello", context)

    assert result.answer == "Direct answer"


def test_direct_answer_counts(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content()])

    result = runtime.run("hello", context)

    assert result.total_llm_calls == 1
    assert result.total_tool_calls == 0
    assert len(result.steps) == 1
    assert result.stopped_reason == "final"


def test_direct_answer_messages_include_system_user_assistant(
    context: ToolContext,
) -> None:
    runtime, _, _ = make_runtime([final_content()])

    result = runtime.run("hello", context)

    assert [message["role"] for message in result.messages] == [
        "system",
        "user",
        "assistant",
    ]


@pytest.mark.parametrize("tool_name", ["calculator", "search", "todo"])
def test_system_prompt_contains_default_tool_schemas(
    context: ToolContext,
    tool_name: str,
) -> None:
    runtime, _, _ = make_runtime([final_content()])

    result = runtime.run("hello", context)

    assert '"name": "{}"'.format(tool_name) in result.messages[0]["content"]


def test_runtime_executes_calculator(context: ToolContext) -> None:
    result, _ = run_calculator_loop(context)

    tool_record = result.steps[0].tool_results[0]
    assert tool_record["tool_name"] == "calculator"
    assert tool_record["result"]["success"] is True
    assert tool_record["result"]["output"]["result"] == 60


def test_single_tool_loop_reaches_second_final(context: ToolContext) -> None:
    result, _ = run_calculator_loop(context)

    assert result.answer == "结果是 60。"
    assert result.total_llm_calls == 2
    assert result.total_tool_calls == 1
    assert [step.decision_type for step in result.steps] == ["tool_call", "final"]


def test_second_llm_call_receives_real_calculator_result(
    context: ToolContext,
) -> None:
    _, fake_client = run_calculator_loop(context)

    second_call_messages = fake_client.calls[1]
    tool_message = second_call_messages[-1]["content"]
    assert second_call_messages[-1]["role"] == "user"
    assert "call_1" in tool_message
    assert "calculator" in tool_message
    assert "60" in tool_message


def test_multiple_tools_execute_in_original_order(context: ToolContext) -> None:
    calls = [
        {"id": "call_search", "name": "search", "arguments": {"query": "FastAPI"}},
        {
            "id": "call_todo",
            "name": "todo",
            "arguments": {"action": "add", "content": "阅读 FastAPI 文档"},
        },
    ]
    runtime, fake_client, _ = make_runtime(
        [tool_call_content(calls), final_content("已搜索并记录待办。")]
    )

    result = runtime.run("搜索并记录", context)

    first_step = result.steps[0]
    assert result.total_tool_calls == 2
    assert [call["name"] for call in first_step.tool_calls] == ["search", "todo"]
    assert [item["tool_name"] for item in first_step.tool_results] == [
        "search",
        "todo",
    ]
    assert "call_search" in fake_client.calls[1][-2]["content"]
    assert "call_todo" in fake_client.calls[1][-1]["content"]


def test_runtime_can_continue_through_multiple_tool_rounds(
    context: ToolContext,
) -> None:
    runtime, _, _ = make_runtime(
        [
            tool_call_content([calculator_call("1 + 1", "call_1")]),
            tool_call_content(
                [
                    {
                        "id": "call_2",
                        "name": "search",
                        "arguments": {"query": "Python"},
                    }
                ]
            ),
            final_content("完成。"),
        ]
    )

    result = runtime.run("do both", context)

    assert result.total_llm_calls == 3
    assert result.total_tool_calls == 2
    assert len(result.steps) == 3
    assert [step.decision_type for step in result.steps] == [
        "tool_call",
        "tool_call",
        "final",
    ]


def test_failed_tool_result_is_returned_to_llm(context: ToolContext) -> None:
    runtime, fake_client, _ = make_runtime(
        [
            tool_call_content([calculator_call("1 / 0")]),
            final_content("该表达式发生除零错误。"),
        ]
    )

    result = runtime.run("divide", context)

    failed_result = result.steps[0].tool_results[0]["result"]
    assert failed_result["success"] is False
    assert result.answer == "该表达式发生除零错误。"
    assert len(fake_client.calls) == 2
    assert '"success": false' in fake_client.calls[1][-1]["content"]


def test_unknown_tool_failure_does_not_crash_runtime(context: ToolContext) -> None:
    unknown_call = {
        "id": "call_unknown",
        "name": "missing_tool",
        "arguments": {},
    }
    runtime, fake_client, _ = make_runtime(
        [tool_call_content([unknown_call]), final_content("工具不存在。")]
    )

    result = runtime.run("unknown", context)

    failed_result = result.steps[0].tool_results[0]["result"]
    assert failed_result["success"] is False
    assert "Unknown tool" in failed_result["error"]
    assert "Unknown tool" in fake_client.calls[1][-1]["content"]


def test_todo_receives_runtime_context(context: ToolContext) -> None:
    todo_call = {
        "id": "call_todo",
        "name": "todo",
        "arguments": {"action": "add", "content": "Context item"},
    }
    runtime, _, registry = make_runtime(
        [tool_call_content([todo_call]), final_content("已添加。")]
    )

    runtime.run("add todo", context)

    todo_tool = registry.get("todo")
    same_scope = todo_tool.execute({"action": "list"}, context)
    other_user = todo_tool.execute(
        {"action": "list"},
        ToolContext(user_id="user-2", session_id=context.session_id),
    )
    other_session = todo_tool.execute(
        {"action": "list"},
        ToolContext(user_id=context.user_id, session_id="session-2"),
    )
    assert [item["content"] for item in same_scope.output["todos"]] == ["Context item"]
    assert other_user.output["todos"] == []
    assert other_session.output["todos"] == []


def test_same_runtime_isolates_todos_between_contexts() -> None:
    responses = [
        tool_call_content(
            [
                {
                    "id": "call_1",
                    "name": "todo",
                    "arguments": {"action": "add", "content": "First"},
                }
            ]
        ),
        final_content("first done"),
        tool_call_content(
            [
                {
                    "id": "call_2",
                    "name": "todo",
                    "arguments": {"action": "add", "content": "Second"},
                }
            ]
        ),
        final_content("second done"),
    ]
    runtime, _, registry = make_runtime(responses)
    first_context = ToolContext("user", "session-1")
    second_context = ToolContext("user", "session-2")

    runtime.run("first", first_context)
    runtime.run("second", second_context)

    todo_tool = registry.get("todo")
    first_todos = todo_tool.execute({"action": "list"}, first_context).output["todos"]
    second_todos = todo_tool.execute({"action": "list"}, second_context).output["todos"]
    assert [item["content"] for item in first_todos] == ["First"]
    assert [item["content"] for item in second_todos] == ["Second"]


@pytest.mark.parametrize(
    "llm_error",
    [
        LLMConfigurationError("secret configuration detail"),
        LLMRequestError("secret request detail"),
        LLMResponseError("secret response detail"),
    ],
)
def test_llm_errors_are_converted(
    context: ToolContext,
    llm_error: Exception,
) -> None:
    runtime, _, _ = make_runtime([llm_error])

    with pytest.raises(AgentLLMError) as error_info:
        runtime.run("hello", context)

    assert "secret" not in str(error_info.value)


def test_parse_failure_becomes_decision_error(context: ToolContext) -> None:
    runtime, _, _ = make_runtime(["not JSON"])

    with pytest.raises(AgentDecisionError, match="could not be parsed"):
        runtime.run("hello", context)


def test_max_steps_stops_loop(context: ToolContext) -> None:
    response = tool_call_content([calculator_call("1 + 1")])
    runtime, fake_client, _ = make_runtime([response, response], max_steps=2)

    with pytest.raises(AgentMaxStepsError, match="max_steps=2"):
        runtime.run("keep going", context)

    assert len(fake_client.calls) == 2


def test_agent_step_to_dict() -> None:
    step = AgentStep(
        step_number=1,
        decision_type="final",
        reasoning_summary="short summary",
        model="model",
    )

    assert step.to_dict() == {
        "step_number": 1,
        "decision_type": "final",
        "reasoning_summary": "short summary",
        "tool_calls": [],
        "tool_results": [],
        "model": "model",
    }


def test_agent_run_result_to_dict(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content("answer")])

    result_dict = runtime.run("hello", context).to_dict()

    assert result_dict["answer"] == "answer"
    assert result_dict["total_llm_calls"] == 1
    assert result_dict["total_tool_calls"] == 0
    assert result_dict["stopped_reason"] == "final"
    assert result_dict["steps"][0]["decision_type"] == "final"


def test_result_does_not_record_chain_of_thought(context: ToolContext) -> None:
    runtime, _, _ = make_runtime([final_content()])

    serialized_result = json.dumps(runtime.run("hello", context).to_dict())

    assert "chain_of_thought" not in serialized_result
    assert '"thoughts"' not in serialized_result
    assert "reasoning_summary" in serialized_result


def test_result_redacts_api_key(context: ToolContext) -> None:
    secret = "runtime-secret-api-key"
    config = LLMConfig(secret, "https://llm.invalid/v1", "test-model")
    secret_final = json.dumps(
        {
            "type": "final",
            "reasoning_summary": "secret is {}".format(secret),
            "answer": "answer contains {}".format(secret),
        }
    )
    runtime, _, _ = make_runtime([secret_final], config=config)

    serialized_result = json.dumps(runtime.run(secret, context).to_dict())

    assert secret not in serialized_result
    assert "[REDACTED]" in serialized_result


def test_runtime_does_not_close_external_client(context: ToolContext) -> None:
    runtime, fake_client, _ = make_runtime([final_content()])

    runtime.run("hello", context)

    assert fake_client.closed is False

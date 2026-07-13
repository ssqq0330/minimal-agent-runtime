"""Tests for structured Agent decision parsing."""

import json
from typing import Any, Dict

import pytest

from app.agent import (
    AgentDecision,
    AgentOutputParseError,
    ParsedToolCall,
    parse_llm_output,
)


FINAL_DATA: Dict[str, Any] = {
    "type": "final",
    "reasoning_summary": "无需调用工具。",
    "answer": "这是最终答案。",
}
TOOL_CALL_DATA: Dict[str, Any] = {
    "type": "tool_call",
    "reasoning_summary": "需要进行计算。",
    "tool_calls": [
        {
            "id": "call_1",
            "name": "calculator",
            "arguments": {"expression": "12 * (3 + 2)"},
        }
    ],
}


def parse_data(data: Any) -> AgentDecision:
    """Serialize test data before passing it through the public parser."""
    return parse_llm_output(json.dumps(data, ensure_ascii=False))


def test_parse_valid_final() -> None:
    decision = parse_data(FINAL_DATA)

    assert decision.type == "final"
    assert decision.answer == "这是最终答案。"
    assert decision.tool_calls == []


def test_parse_valid_single_tool_call() -> None:
    decision = parse_data(TOOL_CALL_DATA)

    assert decision.type == "tool_call"
    assert decision.answer is None
    assert decision.tool_calls[0].name == "calculator"
    assert decision.tool_calls[0].arguments == {"expression": "12 * (3 + 2)"}


def test_parse_multiple_tool_calls() -> None:
    data = {
        "type": "tool_call",
        "reasoning_summary": "需要搜索并添加待办。",
        "tool_calls": [
            {"id": "call_1", "name": "search", "arguments": {"query": "东京天气"}},
            {
                "id": "call_2",
                "name": "todo",
                "arguments": {"action": "add", "content": "携带雨伞"},
            },
        ],
    }

    decision = parse_data(data)

    assert [tool_call.name for tool_call in decision.tool_calls] == ["search", "todo"]


def test_is_final_property() -> None:
    assert parse_data(FINAL_DATA).is_final is True
    assert parse_data(TOOL_CALL_DATA).is_final is False


def test_requires_tools_property() -> None:
    assert parse_data(FINAL_DATA).requires_tools is False
    assert parse_data(TOOL_CALL_DATA).requires_tools is True


def test_decision_to_dict() -> None:
    decision = parse_data(TOOL_CALL_DATA)

    assert decision.to_dict() == {
        "type": "tool_call",
        "reasoning_summary": "需要进行计算。",
        "answer": None,
        "tool_calls": [
            {
                "id": "call_1",
                "name": "calculator",
                "arguments": {"expression": "12 * (3 + 2)"},
            }
        ],
    }


def test_parsed_tool_call_to_dict() -> None:
    tool_call = ParsedToolCall(" call_1 ", " calculator ", {"expression": "1+1"})

    assert tool_call.to_dict() == {
        "id": "call_1",
        "name": "calculator",
        "arguments": {"expression": "1+1"},
    }


def test_parse_markdown_json_code_block() -> None:
    content = "```json\n{}\n```".format(json.dumps(FINAL_DATA, ensure_ascii=False))

    assert parse_llm_output(content).is_final is True


def test_parse_plain_markdown_code_block() -> None:
    content = "```\n{}\n```".format(json.dumps(FINAL_DATA, ensure_ascii=False))

    assert parse_llm_output(content).answer == "这是最终答案。"


def test_extract_json_between_explanatory_text() -> None:
    content = "下面是结果：\n{}\n请根据结果继续。".format(
        json.dumps(FINAL_DATA, ensure_ascii=False)
    )

    assert parse_llm_output(content).type == "final"


def test_json_string_can_contain_braces() -> None:
    data = dict(FINAL_DATA, answer='JSON 对象可以写成 {"name":"Agent"}')

    assert parse_data(data).answer == 'JSON 对象可以写成 {"name":"Agent"}'


def test_json_can_contain_nested_objects() -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [
        {
            "id": "call_1",
            "name": "search",
            "arguments": {"filters": {"language": "zh", "active": True}},
        }
    ]

    decision = parse_data(data)

    assert decision.tool_calls[0].arguments["filters"]["language"] == "zh"


def test_json_can_contain_arrays() -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [
        {
            "id": "call_1",
            "name": "search",
            "arguments": {"keywords": ["Agent", "Runtime"]},
        }
    ]

    assert parse_data(data).tool_calls[0].arguments["keywords"] == ["Agent", "Runtime"]


@pytest.mark.parametrize("content", ["", "   \n\t"])
def test_empty_output_fails(content: str) -> None:
    with pytest.raises(AgentOutputParseError, match="must not be empty"):
        parse_llm_output(content)


def test_non_string_output_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="must be a string"):
        parse_llm_output(123)  # type: ignore[arg-type]


def test_output_without_json_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="No valid JSON object"):
        parse_llm_output("There is no structured decision here.")


def test_malformed_json_fails() -> None:
    with pytest.raises(AgentOutputParseError):
        parse_llm_output('{"type": "final", "answer": }')


def test_top_level_array_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="must be an object"):
        parse_llm_output('[{"type": "final"}]')


def test_missing_type_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="'type'.*missing"):
        parse_data({"reasoning_summary": "summary", "answer": "answer"})


def test_non_string_type_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="type.*string"):
        parse_data({"type": 1, "reasoning_summary": "summary", "answer": "answer"})


def test_invalid_type_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="final.*tool_call"):
        parse_data({"type": "other", "reasoning_summary": "summary"})


def test_missing_reasoning_summary_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="reasoning_summary.*missing"):
        parse_data({"type": "final", "answer": "answer"})


def test_non_string_reasoning_summary_fails() -> None:
    with pytest.raises(AgentOutputParseError, match="reasoning_summary.*string"):
        parse_data({"type": "final", "reasoning_summary": 1, "answer": "answer"})


@pytest.mark.parametrize("summary", ["", "   "])
def test_blank_reasoning_summary_fails(summary: str) -> None:
    with pytest.raises(AgentOutputParseError, match="reasoning_summary.*empty"):
        parse_data({"type": "final", "reasoning_summary": summary, "answer": "answer"})


def test_final_requires_answer() -> None:
    with pytest.raises(AgentOutputParseError, match="'answer'.*missing"):
        parse_data({"type": "final", "reasoning_summary": "summary"})


def test_final_answer_must_be_string() -> None:
    with pytest.raises(AgentOutputParseError, match="answer.*string"):
        parse_data({"type": "final", "reasoning_summary": "summary", "answer": 1})


@pytest.mark.parametrize("answer", ["", "  "])
def test_final_answer_must_not_be_blank(answer: str) -> None:
    with pytest.raises(AgentOutputParseError, match="answer.*empty"):
        parse_data({"type": "final", "reasoning_summary": "summary", "answer": answer})


def test_final_rejects_non_empty_tool_calls() -> None:
    data = dict(FINAL_DATA, tool_calls=[TOOL_CALL_DATA["tool_calls"][0]])

    with pytest.raises(AgentOutputParseError, match="empty list"):
        parse_data(data)


def test_final_accepts_empty_tool_calls() -> None:
    decision = parse_data(dict(FINAL_DATA, tool_calls=[]))

    assert decision.tool_calls == []


def test_tool_call_requires_tool_calls() -> None:
    with pytest.raises(AgentOutputParseError, match="tool_calls.*missing"):
        parse_data({"type": "tool_call", "reasoning_summary": "summary"})


def test_tool_calls_must_be_list() -> None:
    with pytest.raises(AgentOutputParseError, match="tool_calls.*list"):
        parse_data(
            {"type": "tool_call", "reasoning_summary": "summary", "tool_calls": {}}
        )


def test_tool_calls_must_not_be_empty() -> None:
    with pytest.raises(AgentOutputParseError, match="tool_calls.*empty"):
        parse_data(
            {"type": "tool_call", "reasoning_summary": "summary", "tool_calls": []}
        )


def test_tool_call_item_must_be_object() -> None:
    with pytest.raises(AgentOutputParseError, match=r"tool_calls\[0\].*object"):
        parse_data(
            {
                "type": "tool_call",
                "reasoning_summary": "summary",
                "tool_calls": ["invalid"],
            }
        )


@pytest.mark.parametrize("field_name", ["id", "name", "arguments"])
def test_tool_call_requires_each_field(field_name: str) -> None:
    tool_call = {"id": "call_1", "name": "calculator", "arguments": {}}
    del tool_call[field_name]

    with pytest.raises(AgentOutputParseError, match="missing '{}'".format(field_name)):
        parse_data(
            {
                "type": "tool_call",
                "reasoning_summary": "summary",
                "tool_calls": [tool_call],
            }
        )


def test_tool_call_id_must_be_string() -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [{"id": 1, "name": "calculator", "arguments": {}}]

    with pytest.raises(AgentOutputParseError, match="id.*string"):
        parse_data(data)


@pytest.mark.parametrize("tool_call_id", ["", "  "])
def test_tool_call_id_must_not_be_blank(tool_call_id: str) -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [
        {"id": tool_call_id, "name": "calculator", "arguments": {}}
    ]

    with pytest.raises(AgentOutputParseError, match="id.*empty"):
        parse_data(data)


def test_tool_call_name_must_be_string() -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [{"id": "call_1", "name": 1, "arguments": {}}]

    with pytest.raises(AgentOutputParseError, match="name.*string"):
        parse_data(data)


@pytest.mark.parametrize("tool_name", ["", "  "])
def test_tool_call_name_must_not_be_blank(tool_name: str) -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [{"id": "call_1", "name": tool_name, "arguments": {}}]

    with pytest.raises(AgentOutputParseError, match="name.*empty"):
        parse_data(data)


def test_tool_call_arguments_must_be_object() -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [
        {"id": "call_1", "name": "calculator", "arguments": "{}"}
    ]

    with pytest.raises(AgentOutputParseError, match="arguments.*object"):
        parse_data(data)


def test_tool_call_rejects_non_null_answer() -> None:
    data = dict(TOOL_CALL_DATA, answer="premature answer")

    with pytest.raises(AgentOutputParseError, match="answer.*null"):
        parse_data(data)


def test_tool_call_accepts_null_answer() -> None:
    decision = parse_data(dict(TOOL_CALL_DATA, answer=None))

    assert decision.answer is None


def test_duplicate_tool_call_ids_fail() -> None:
    data = dict(TOOL_CALL_DATA)
    data["tool_calls"] = [
        {"id": "call_1", "name": "search", "arguments": {}},
        {"id": " call_1 ", "name": "todo", "arguments": {}},
    ]

    with pytest.raises(AgentOutputParseError, match="Duplicate"):
        parse_data(data)


def test_extra_fields_are_ignored() -> None:
    data = dict(FINAL_DATA, extra="ignored")

    decision = parse_data(data)

    assert decision.is_final is True
    assert "extra" not in decision.to_dict()


def test_invalid_braces_before_valid_json_are_skipped() -> None:
    content = "invalid {{not json}} then {}".format(
        json.dumps(FINAL_DATA, ensure_ascii=False)
    )

    assert parse_llm_output(content).answer == "这是最终答案。"


def test_parse_error_does_not_include_long_model_output() -> None:
    long_output = "sensitive-prefix-" + ("x" * 5000)

    with pytest.raises(AgentOutputParseError) as error_info:
        parse_llm_output(long_output)

    error_message = str(error_info.value)
    assert len(error_message) < 200
    assert "sensitive-prefix" not in error_message

"""Tests for Agent system and tool-result prompt builders."""

import json
from typing import Any, Dict, List

import pytest

from app.agent import build_agent_system_prompt, build_tool_result_message
from app.tools import create_default_registry


@pytest.fixture
def tool_schemas() -> List[Dict[str, Any]]:
    """Return schemas for the three default tools."""
    return create_default_registry().get_tool_schemas()


@pytest.fixture
def system_prompt(tool_schemas: List[Dict[str, Any]]) -> str:
    """Build one prompt shared by prompt-content tests."""
    return build_agent_system_prompt(tool_schemas)


@pytest.mark.parametrize("tool_name", ["calculator", "search", "todo"])
def test_default_tool_names_appear_in_prompt(
    system_prompt: str,
    tool_name: str,
) -> None:
    assert '"name": "{}"'.format(tool_name) in system_prompt


@pytest.mark.parametrize("schema_index", [0, 1, 2])
def test_complete_tool_schema_appears_in_prompt(
    system_prompt: str,
    tool_schemas: List[Dict[str, Any]],
    schema_index: int,
) -> None:
    serialized_tool_list = system_prompt.split("可用工具 Schema：\n", 1)[1]
    embedded_schemas = json.loads(serialized_tool_list)
    assert embedded_schemas[schema_index] == tool_schemas[schema_index]


def test_prompt_contains_final_protocol(system_prompt: str) -> None:
    assert '"type": "final"' in system_prompt
    assert '"answer"' in system_prompt


def test_prompt_contains_tool_call_protocol(system_prompt: str) -> None:
    assert '"type": "tool_call"' in system_prompt
    assert '"tool_calls"' in system_prompt


def test_prompt_requires_single_json_object(system_prompt: str) -> None:
    assert "只能输出一个 JSON object" in system_prompt


def test_prompt_forbids_markdown(system_prompt: str) -> None:
    assert "不要输出 Markdown" in system_prompt


def test_prompt_forbids_invented_tool_results(system_prompt: str) -> None:
    assert "不得虚构工具执行结果" in system_prompt
    assert "不能声称工具执行成功" in system_prompt


def test_prompt_requires_arguments_object(system_prompt: str) -> None:
    assert "arguments 必须是 JSON object" in system_prompt
    assert "不要把 arguments 输出为字符串" in system_prompt


def test_prompt_forbids_full_chain_of_thought(system_prompt: str) -> None:
    assert "不要输出完整内部思维链" in system_prompt


def test_prompt_defaults_to_chinese_for_chinese_users(system_prompt: str) -> None:
    assert "中文用户默认使用中文回复" in system_prompt


def test_prompt_explains_mutually_exclusive_fields(system_prompt: str) -> None:
    assert "tool_call 模式不输出 answer" in system_prompt
    assert "final 模式不输出非空 tool_calls" in system_prompt


def test_tool_schemas_must_be_list() -> None:
    with pytest.raises(ValueError, match="must be a list"):
        build_agent_system_prompt({})  # type: ignore[arg-type]


def test_each_tool_schema_must_be_object() -> None:
    with pytest.raises(ValueError, match=r"tool_schemas\[1\].*object"):
        build_agent_system_prompt([{}, "invalid"])  # type: ignore[list-item]


@pytest.fixture
def tool_result_message() -> str:
    """Build a representative successful tool result message."""
    return build_tool_result_message(
        "call_1",
        "calculator",
        {
            "success": True,
            "output": {"result": 60, "说明": "计算成功"},
            "error": None,
        },
    )


def test_tool_result_contains_call_id(tool_result_message: str) -> None:
    assert '"tool_call_id": "call_1"' in tool_result_message


def test_tool_result_contains_tool_name(tool_result_message: str) -> None:
    assert '"tool_name": "calculator"' in tool_result_message


def test_tool_result_contains_success(tool_result_message: str) -> None:
    assert '"success": true' in tool_result_message


def test_tool_result_contains_output(tool_result_message: str) -> None:
    assert '"output"' in tool_result_message
    assert '"result": 60' in tool_result_message


def test_tool_result_contains_error(tool_result_message: str) -> None:
    assert '"error": null' in tool_result_message


def test_tool_result_preserves_chinese(tool_result_message: str) -> None:
    assert "计算成功" in tool_result_message
    assert "\\u8ba1" not in tool_result_message


def test_tool_result_tells_model_to_continue(tool_result_message: str) -> None:
    assert "继续调用工具" in tool_result_message
    assert "返回 final" in tool_result_message
    assert "不要虚构、修改或伪造工具结果" in tool_result_message


@pytest.mark.parametrize("tool_call_id", ["", "   "])
def test_tool_result_requires_call_id(tool_call_id: str) -> None:
    with pytest.raises(ValueError, match="tool_call_id"):
        build_tool_result_message(tool_call_id, "calculator", {})


@pytest.mark.parametrize("tool_name", ["", "   "])
def test_tool_result_requires_tool_name(tool_name: str) -> None:
    with pytest.raises(ValueError, match="tool_name"):
        build_tool_result_message("call_1", tool_name, {})


def test_tool_result_requires_result_object() -> None:
    with pytest.raises(ValueError, match="result.*object"):
        build_tool_result_message("call_1", "calculator", "invalid")  # type: ignore[arg-type]

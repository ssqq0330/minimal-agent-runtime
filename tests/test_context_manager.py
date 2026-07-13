"""Tests for deterministic Session context normalization and compression."""

import copy
import json

import pytest

from app.memory import (
    BasicContextManager,
    ContextBuildResult,
    ContextCompressionError,
    ContextConfig,
    MessageRecord,
    estimate_messages_chars,
)
from app.memory.context import (
    CONTEXT_TRUNCATION_MARKER,
    MESSAGE_TRUNCATION_MARKER,
    SUMMARY_TITLE,
    SUMMARY_TRUNCATION_MARKER,
)


def message(role, content, **extra):
    value = {"role": role, "content": content}
    value.update(extra)
    return value


def compact_config(**overrides):
    values = {
        "max_messages": 4,
        "recent_messages": 2,
        "max_chars": 1000,
        "summary_max_chars": 300,
        "per_message_chars": 100,
    }
    values.update(overrides)
    return ContextConfig(**values)


def test_default_config_is_valid():
    config = ContextConfig()
    assert config.max_messages == 20
    assert config.recent_messages == 8
    assert config.max_chars == 12000


@pytest.mark.parametrize(
    ("field", "value", "message_fragment"),
    [
        ("max_messages", 0, "greater than 0"),
        ("max_messages", True, "integer"),
        ("recent_messages", 0, "greater than 0"),
        ("max_chars", 0, "greater than 0"),
        ("summary_max_chars", "10", "integer"),
        ("per_message_chars", 1.5, "integer"),
    ],
)
def test_config_rejects_non_positive_bool_and_non_integer_values(
    field, value, message_fragment
):
    values = ContextConfig().__dict__
    values[field] = value
    with pytest.raises(ValueError, match=message_fragment):
        ContextConfig(**values)


def test_config_rejects_invalid_cross_field_limits():
    with pytest.raises(ValueError, match="recent_messages"):
        compact_config(max_messages=2, recent_messages=3)
    with pytest.raises(ValueError, match="summary_max_chars"):
        compact_config(max_chars=300, summary_max_chars=300)
    with pytest.raises(ValueError, match="per_message_chars"):
        compact_config(summary_max_chars=50, per_message_chars=51)


def test_manager_rejects_invalid_config_object():
    with pytest.raises(ValueError, match="ContextConfig"):
        BasicContextManager({})


def test_empty_history_returns_empty_uncompressed_result():
    result = BasicContextManager().build([])
    assert result.messages == []
    assert result.compressed is False
    assert result.original_message_count == 0
    assert result.output_message_count == 0
    assert result.retained_recent_count == 0
    assert result.output_char_count == 0
    assert result.summary_text is None


def test_history_must_be_a_list():
    with pytest.raises(ContextCompressionError, match="history must be a list"):
        BasicContextManager().build((message("user", "hello"),))


def test_dict_and_message_record_are_normalized_without_metadata():
    record = MessageRecord(
        id=1,
        user_id="u",
        session_id="s",
        role="assistant",
        content="  北京天气晴朗  ",
        created_at="2026-07-13T00:00:00Z",
        metadata={"reasoning_summary": "secret", "used_tools": ["search"]},
    )
    result = BasicContextManager().build(
        [
            message("user", "  添加 Todo：周五前完成周报  ", api_key="sk-secret"),
            record,
        ]
    )
    assert result.messages == [
        message("user", "添加 Todo：周五前完成周报"),
        message("assistant", "北京天气晴朗"),
    ]
    serialized = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "metadata" not in serialized
    assert "reasoning_summary" not in serialized
    assert "used_tools" not in serialized
    assert "sk-secret" not in serialized


@pytest.mark.parametrize("bad_item", [None, "message", 3, object()])
def test_invalid_history_item_type_fails(bad_item):
    with pytest.raises(ContextCompressionError, match="MessageRecord or dictionary"):
        BasicContextManager().build([bad_item])


@pytest.mark.parametrize(
    ("bad_message", "error"),
    [
        ({"content": "hello"}, "missing role"),
        ({"role": "system", "content": "hello"}, "user.*assistant"),
        ({"role": [], "content": "hello"}, "role must be a string"),
        ({"role": "user"}, "missing content"),
        ({"role": "user", "content": 12}, "content must be a string"),
        ({"role": "assistant", "content": " \n\t "}, "must not be empty"),
    ],
)
def test_invalid_message_fields_fail_clearly(bad_message, error):
    with pytest.raises(ContextCompressionError, match=error):
        BasicContextManager().build([bad_message])


def test_build_does_not_modify_history_or_message_dictionaries():
    history = [
        message("user", "  first  ", metadata={"nested": [1, 2]}),
        message("assistant", "second", ignored=True),
    ]
    original = copy.deepcopy(history)
    result = BasicContextManager().build(history)
    assert history == original
    assert result.messages is not history
    assert result.messages[0] is not history[0]


def test_history_within_both_limits_is_returned_in_order():
    history = [message("user", "one"), message("assistant", "two")]
    result = BasicContextManager(compact_config()).build(history)
    assert result.messages == history
    assert result.compressed is False
    assert result.summary_text is None
    assert result.summarized_message_count == 0
    assert result.retained_recent_count == 2
    assert result.output_char_count == estimate_messages_chars(result.messages)


def test_message_count_limit_triggers_summary_and_retains_latest_in_order():
    history = [
        message("user", "旧问题一"),
        message("assistant", "旧回答一"),
        message("user", "旧问题二"),
        message("assistant", "较新回答"),
        message("user", "最新问题"),
    ]
    result = BasicContextManager(compact_config()).build(history)
    assert result.compressed is True
    assert result.messages[0]["role"] == "assistant"
    assert result.messages[0]["content"].startswith(SUMMARY_TITLE)
    assert result.messages[1:] == history[-2:]
    assert result.summarized_message_count == 3
    assert result.retained_recent_count == 2
    assert result.output_message_count == 3
    assert "1. 用户：旧问题一" in result.summary_text
    assert "2. 助手：旧回答一" in result.summary_text


def test_character_limit_triggers_even_below_message_count_limit():
    history = [message("user", "A" * 170), message("assistant", "newest")]
    config = compact_config(
        max_messages=4,
        recent_messages=1,
        max_chars=150,
        summary_max_chars=80,
        per_message_chars=50,
    )
    result = BasicContextManager(config).build(history)
    assert result.compressed is True
    assert result.messages[-1] == history[-1]
    assert result.output_char_count <= config.max_chars
    assert "A" in result.summary_text


def test_older_recent_message_is_truncated_before_newest_message():
    history = [
        message("user", "summary source"),
        message("assistant", "O" * 100),
        message("user", "newest remains whole"),
    ]
    config = compact_config(
        max_messages=3,
        recent_messages=2,
        max_chars=130,
        summary_max_chars=60,
        per_message_chars=30,
    )
    result = BasicContextManager(config).build(history)
    assert result.compressed is True
    assert len(result.messages[1]["content"]) < 100
    assert result.messages[-1]["content"] == "newest remains whole"
    assert result.output_char_count <= config.max_chars


def test_summary_preserves_chinese_todo_city_and_role_labels():
    history = [
        message("user", "请添加 Todo：周五前完成周报，并查询上海天气"),
        message("assistant", "已添加待办，上海今天有雨"),
        message("user", "next one"),
        message("assistant", "next two"),
        message("user", "latest"),
    ]
    result = BasicContextManager(compact_config()).build(history)
    summary = result.summary_text
    assert "用户：" in summary
    assert "助手：" in summary
    assert "Todo：周五前完成周报" in summary
    assert "上海" in summary
    assert "不存在的信息" not in summary
    assert "\\u" not in summary


def test_each_old_message_is_truncated_before_entering_summary():
    history = [
        message("user", "abcdefghijklmno"),
        message("assistant", "old answer"),
        message("user", "recent one"),
        message("assistant", "recent two"),
        message("user", "recent three"),
    ]
    config = compact_config(per_message_chars=12)
    result = BasicContextManager(config).build(history)
    assert MESSAGE_TRUNCATION_MARKER in result.summary_text
    assert "abcdefghijklmno" not in result.summary_text


def test_total_summary_is_capped_and_has_further_compression_marker():
    history = [
        message("user" if index % 2 == 0 else "assistant", str(index) + "X" * 80)
        for index in range(8)
    ]
    config = compact_config(
        max_messages=4,
        recent_messages=1,
        summary_max_chars=100,
        per_message_chars=40,
    )
    result = BasicContextManager(config).build(history)
    assert len(result.summary_text) <= config.summary_max_chars
    assert SUMMARY_TRUNCATION_MARKER in result.summary_text


def test_metadata_secrets_and_runtime_details_never_enter_summary():
    history = [
        message(
            "user",
            "普通问题",
            metadata={
                "reasoning_summary": "private reasoning",
                "used_tools": ["calculator"],
                "api_key": "sk-do-not-copy",
                "authorization": "Bearer hidden",
                "runtime_messages": [{"tool": "raw result"}],
            },
        ),
        message("assistant", "普通回答", metadata={"http_response": "raw"}),
        message("user", "recent one"),
        message("assistant", "recent two"),
        message("user", "recent three"),
    ]
    result = BasicContextManager(compact_config()).build(history)
    payload = json.dumps(result.to_dict(), ensure_ascii=False)
    for forbidden in (
        "private reasoning",
        "used_tools",
        "sk-do-not-copy",
        "Bearer hidden",
        "raw result",
        "http_response",
    ):
        assert forbidden not in payload


def test_extremely_long_recent_messages_remain_valid_and_counted_exactly():
    history = [message("user", "U" * 500), message("assistant", "A" * 500)]
    config = compact_config(
        max_messages=4,
        recent_messages=2,
        max_chars=100,
        summary_max_chars=30,
        per_message_chars=20,
    )
    result = BasicContextManager(config).build(history)
    assert result.compressed is True
    assert result.output_char_count <= config.max_chars
    assert all(item["role"] in {"user", "assistant"} for item in result.messages)
    assert all(item["content"] for item in result.messages)
    assert result.output_char_count == estimate_messages_chars(result.messages)
    assert min(
        len(result.messages[1]["content"]),
        len(result.messages[2]["content"]),
    ) < 500


def test_context_truncation_marker_is_used_when_there_is_room():
    history = [message("user", "U" * 80), message("assistant", "latest")]
    config = compact_config(
        max_messages=4,
        recent_messages=2,
        max_chars=115,
        summary_max_chars=30,
        per_message_chars=20,
    )
    result = BasicContextManager(config).build(history)
    assert CONTEXT_TRUNCATION_MARKER in result.messages[1]["content"]


def test_tiny_max_chars_terminates_with_non_empty_legal_messages():
    config = ContextConfig(
        max_messages=1,
        recent_messages=1,
        max_chars=3,
        summary_max_chars=2,
        per_message_chars=1,
    )
    result = BasicContextManager(config).build([message("user", "very long")])
    assert result.compressed is True
    assert all(item["content"] for item in result.messages)
    assert all(item["role"] in {"user", "assistant"} for item in result.messages)
    assert result.original_message_count >= 0
    assert result.output_message_count >= 0
    assert result.summarized_message_count >= 0
    assert result.retained_recent_count >= 0
    assert result.output_char_count == estimate_messages_chars(result.messages)


def test_single_oversized_message_is_supported():
    config = compact_config(
        max_messages=4,
        recent_messages=2,
        max_chars=90,
        summary_max_chars=30,
        per_message_chars=20,
    )
    result = BasicContextManager(config).build([message("user", "Z" * 300)])
    assert result.compressed is True
    assert result.summarized_message_count == 0
    assert result.retained_recent_count == 1
    assert result.messages[-1]["content"]


def test_previously_generated_summary_is_flattened_on_recompression():
    manager = BasicContextManager(compact_config())
    first_history = [
        message("user", "old one"),
        message("assistant", "old two"),
        message("user", "middle one"),
        message("assistant", "middle two"),
        message("user", "recent"),
    ]
    first = manager.build(first_history)
    second_input = first.messages + [
        message("assistant", "new answer"),
        message("user", "new question"),
        message("assistant", "newest answer"),
    ]
    second = manager.build(second_input)
    summaries = [
        item
        for item in second.messages
        if item["content"].startswith(SUMMARY_TITLE)
    ]
    assert second.compressed is True
    assert len(summaries) == 1
    assert second.summary_text.count(SUMMARY_TITLE) == 1
    assert second.messages[-2:] == second_input[-2:]
    assert "old one" in second.summary_text
    assert "new answer" in second.summary_text


def test_repeated_build_without_new_overflow_keeps_one_summary():
    manager = BasicContextManager(compact_config())
    history = [message("user", str(index)) for index in range(5)]
    first = manager.build(history)
    second = manager.build(first.messages)
    assert sum(
        item["content"].startswith(SUMMARY_TITLE) for item in second.messages
    ) == 1
    assert second.messages[-1]["content"] == "4"


def test_result_to_dict_is_independent_json_serializable_plain_data():
    source_messages = [message("user", "hello", metadata={"secret": True})]
    result = ContextBuildResult(
        messages=source_messages,
        compressed=False,
        original_message_count=1,
        output_message_count=1,
        summarized_message_count=0,
        retained_recent_count=1,
        original_char_count=21,
        output_char_count=21,
    )
    value = result.to_dict()
    assert value["summary_text"] is None
    assert value["messages"] == [message("user", "hello")]
    assert json.loads(json.dumps(value)) == value
    value["messages"][0]["content"] = "changed"
    assert result.messages[0]["content"] == "hello"


def test_estimator_handles_empty_and_normal_messages_without_mutation():
    assert estimate_messages_chars([]) == 0
    messages = [message("user", "hello"), message("assistant", "你好")]
    original = copy.deepcopy(messages)
    assert estimate_messages_chars(messages) > 0
    assert estimate_messages_chars(messages) == sum(
        len(item["role"]) + len(item["content"]) + 12 for item in messages
    )
    assert messages == original


@pytest.mark.parametrize("bad_messages", [None, {}, [None], [{"role": "user"}]])
def test_estimator_rejects_malformed_input(bad_messages):
    with pytest.raises(ContextCompressionError):
        estimate_messages_chars(bad_messages)

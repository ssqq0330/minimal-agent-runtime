"""Offline integration tests for Session recall through BasicContextManager."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional, Union

import pytest

from app.agent import (
    AgentDecisionError,
    AgentLLMError,
    AgentMaxStepsError,
    AgentRuntime,
    SessionAgentService,
)
from app.llm import LLMRequestError, LLMResponse
from app.memory import (
    BasicContextManager,
    ContextCompressionError,
    ContextConfig,
    MessageRecord,
    SQLiteStore,
)
from app.tools import create_default_registry
from scripts import context_compression_demo


FakeResponse = Union[str, Exception]


def final_content(answer: str = "最终回答") -> str:
    return json.dumps(
        {
            "type": "final",
            "reasoning_summary": "可以回答。",
            "answer": answer,
        },
        ensure_ascii=False,
    )


def tool_content(name: str, arguments: Dict[str, object]) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "reasoning_summary": "需要工具。",
            "tool_calls": [
                {"id": "call-1", "name": name, "arguments": arguments}
            ],
        },
        ensure_ascii=False,
    )


class FakeLLMClient:
    """Return deterministic responses while recording LLM message snapshots."""

    def __init__(self, responses: List[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: List[List[Dict[str, str]]] = []

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(content=response, model="fake-model")


class RecordingContextManager(BasicContextManager):
    """Record raw recalled messages before using the real implementation."""

    def __init__(self, config: ContextConfig) -> None:
        super().__init__(config)
        self.inputs: List[List[MessageRecord]] = []

    def build(self, history):  # type: ignore[no-untyped-def]
        self.inputs.append(list(history))
        return super().build(history)


class FailingContextManager(BasicContextManager):
    def build(self, history):  # type: ignore[no-untyped-def]
        raise ContextCompressionError("Context history is invalid.")


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "context-integration" / "agent.db")


def make_service(
    store: SQLiteStore,
    responses: List[FakeResponse],
    config: Optional[ContextConfig] = None,
    history_limit: Optional[int] = None,
    max_steps: int = 8,
    context_manager: Optional[BasicContextManager] = None,
):
    client = FakeLLMClient(responses)
    runtime = AgentRuntime(  # type: ignore[arg-type]
        client,
        create_default_registry(todo_store=store),
        max_steps=max_steps,
    )
    manager = context_manager or BasicContextManager(config)
    service = SessionAgentService(
        runtime,
        store,
        history_limit=history_limit,
        context_manager=manager,
    )
    return service, client, manager


def seed_exchanges(
    store: SQLiteStore,
    user_id: str,
    session_id: str,
    count: int,
    prefix: str = "history",
) -> None:
    for index in range(1, count + 1):
        store.add_exchange(
            user_id,
            session_id,
            "{} question {}".format(prefix, index),
            "{} answer {}".format(prefix, index),
        )


def compression_config(**overrides) -> ContextConfig:
    values = {
        "max_messages": 4,
        "recent_messages": 2,
        "max_chars": 1000,
        "summary_max_chars": 400,
        "per_message_chars": 100,
    }
    values.update(overrides)
    return ContextConfig(**values)


def test_initialization_creates_default_or_accepts_injected_manager_without_io(
    store: SQLiteStore,
) -> None:
    client = FakeLLMClient([final_content()])
    runtime = AgentRuntime(  # type: ignore[arg-type]
        client,
        create_default_registry(todo_store=store),
    )
    default_service = SessionAgentService(runtime, store)
    custom = BasicContextManager(compression_config())
    custom_service = SessionAgentService(runtime, store, context_manager=custom)

    assert isinstance(default_service.context_manager, BasicContextManager)
    assert custom_service.context_manager is custom
    assert client.calls == []
    assert store.list_sessions("user") == []


def test_initialization_rejects_invalid_context_manager(store: SQLiteStore) -> None:
    _, _, manager = make_service(store, [final_content()])
    client = FakeLLMClient([final_content()])
    runtime = AgentRuntime(client, create_default_registry())  # type: ignore[arg-type]
    assert isinstance(manager, BasicContextManager)
    with pytest.raises(TypeError, match="context_manager"):
        SessionAgentService(runtime, store, context_manager=object())  # type: ignore[arg-type]


def test_empty_history_builds_uncompressed_context_and_saves_one_exchange(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    service, client, _ = make_service(store, [final_content("你好")])

    result = service.chat("user", "window", "当前问题")

    assert result.loaded_history_count == 0
    assert result.context_result is not None
    assert result.context_result.compressed is False
    assert result.context_compressed is False
    assert result.context_message_count == 0
    assert [item["role"] for item in client.calls[0]] == ["system", "user"]
    assert client.calls[0][-1]["content"] == "当前问题"
    assert store.count_messages("user", "window") == 2
    assert result.assistant_message.metadata["context"]["compressed"] is False


def test_message_count_compression_is_passed_to_runtime_before_current_input(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    seed_exchanges(store, "user", "window", 3)
    service, client, _ = make_service(
        store,
        [final_content()],
        config=compression_config(),
    )

    result = service.chat("user", "window", "current question")
    llm_messages = client.calls[0]
    runtime_history = llm_messages[1:-1]

    assert result.loaded_history_count == 6
    assert result.context_compressed is True
    assert result.context_result.summarized_message_count == 4
    assert result.context_result.retained_recent_count == 2
    assert runtime_history == result.context_result.messages
    assert runtime_history[0]["role"] == "assistant"
    assert runtime_history[0]["content"].startswith("【较早会话摘要】")
    assert [item["content"] for item in runtime_history[-2:]] == [
        "history question 3",
        "history answer 3",
    ]
    assert llm_messages[-1] == {"role": "user", "content": "current question"}


def test_character_compression_preserves_legal_messages_and_latest_history(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    store.add_exchange("user", "window", "O" * 260, "latest answer")
    config = compression_config(
        max_messages=10,
        recent_messages=1,
        max_chars=150,
        summary_max_chars=80,
        per_message_chars=50,
    )
    service, client, _ = make_service(store, [final_content()], config=config)

    result = service.chat("user", "window", "current")

    assert result.context_compressed is True
    assert result.context_result.original_message_count == 2
    assert result.context_result.output_char_count <= config.max_chars
    assert result.context_result.messages[-1]["content"] == "latest answer"
    assert all(item["content"] for item in client.calls[0][1:-1])


def test_compression_never_persists_or_modifies_summary_history(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    seed_exchanges(store, "user", "window", 3)
    before = [
        (item.id, item.role, item.content)
        for item in store.list_messages("user", "window")
    ]
    service, _, _ = make_service(
        store,
        [final_content("turn one"), final_content("turn two")],
        config=compression_config(),
    )

    first = service.chat("user", "window", "new one")
    second = service.chat("user", "window", "new two")
    persisted = store.list_messages("user", "window")

    assert [
        (item.id, item.role, item.content) for item in persisted[: len(before)]
    ] == before
    assert len(persisted) == len(before) + 4
    assert all(not item.content.startswith("【较早会话摘要】") for item in persisted)
    assert sum(
        item["content"].startswith("【较早会话摘要】")
        for item in first.context_result.messages
    ) == 1
    assert sum(
        item["content"].startswith("【较早会话摘要】")
        for item in second.context_result.messages
    ) == 1
    assert second.context_result.messages[-1]["content"] == "turn one"


def test_message_metadata_and_secrets_do_not_enter_runtime_context(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    secret_metadata = {
        "reasoning_summary": "private chain",
        "used_tools": ["secret-tool"],
        "api_key": "sk-context-secret",
        "system_prompt": "hidden prompt",
        "messages": [{"content": "raw tool result"}],
        "http_response": "raw response",
    }
    store.add_message("user", "window", "user", "user text", secret_metadata)
    store.add_message("user", "window", "assistant", "assistant text", secret_metadata)
    service, client, _ = make_service(store, [final_content()])

    result = service.chat("user", "window", "current")
    runtime_history = json.dumps(client.calls[0][1:-1], ensure_ascii=False)
    metadata_json = json.dumps(result.assistant_message.metadata, ensure_ascii=False)

    assert "user text" in runtime_history and "assistant text" in runtime_history
    for forbidden in (
        "private chain",
        "secret-tool",
        "sk-context-secret",
        "hidden prompt",
        "raw tool result",
        "raw response",
    ):
        assert forbidden not in runtime_history
    assert set(result.assistant_message.metadata["context"]) == {
        "compressed",
        "original_message_count",
        "output_message_count",
        "summarized_message_count",
        "retained_recent_count",
        "original_char_count",
        "output_char_count",
    }
    assert "summary_text" not in metadata_json
    assert '"messages"' not in metadata_json
    assert "system_prompt" not in metadata_json


def test_sessions_and_users_remain_isolated_during_compression(
    store: SQLiteStore,
) -> None:
    for user_id, session_id, prefix in (
        ("user-a", "same", "alpha-private"),
        ("user-b", "same", "beta-private"),
        ("user-a", "other", "other-window"),
    ):
        store.create_session(user_id, session_id)
        seed_exchanges(store, user_id, session_id, 2, prefix)
    service, client, _ = make_service(
        store,
        [final_content("a"), final_content("b"), final_content("other")],
        config=compression_config(max_messages=2, recent_messages=1),
    )

    service.chat("user-a", "same", "ask a")
    service.chat("user-b", "same", "ask b")
    service.chat("user-a", "other", "ask other")
    contexts = [json.dumps(call[1:-1], ensure_ascii=False) for call in client.calls]

    assert "alpha-private" in contexts[0] and "beta-private" not in contexts[0]
    assert "beta-private" in contexts[1] and "alpha-private" not in contexts[1]
    assert "other-window" in contexts[2] and "alpha-private" not in contexts[2]
    assert store.count_messages("user-a", "same") == 6
    assert store.count_messages("user-b", "same") == 6


def test_todo_tool_keeps_session_scope_after_history_compression(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    seed_exchanges(store, "user", "window", 3)
    service, client, _ = make_service(
        store,
        [
            tool_content("todo", {"action": "add", "content": "完成 README"}),
            final_content("已添加"),
            final_content("仍记得已添加"),
        ],
        config=compression_config(),
    )

    first = service.chat("user", "window", "添加待办")
    service.chat("user", "window", "刚才做了什么？")

    todos = store.list_todos("user", "window")
    assert [(todo.content, todo.user_id, todo.session_id) for todo in todos] == [
        ("完成 README", "user", "window")
    ]
    assert first.assistant_message.metadata["agent"]["used_tools"] == ["todo"]
    next_history = json.dumps(client.calls[2][1:-1], ensure_ascii=False)
    assert "Tool execution result" not in next_history
    assert "tool_call_id" not in next_history


def test_history_limit_runs_before_context_compression_without_deleting_rows(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    seed_exchanges(store, "user", "window", 10)
    manager = RecordingContextManager(compression_config())
    service, client, _ = make_service(
        store,
        [final_content()],
        history_limit=6,
        context_manager=manager,
    )

    result = service.chat("user", "window", "current")

    assert result.loaded_history_count == 6
    assert len(manager.inputs[0]) == 6
    assert [item.content for item in manager.inputs[0]] == [
        "history question 8",
        "history answer 8",
        "history question 9",
        "history answer 9",
        "history question 10",
        "history answer 10",
    ]
    assert result.context_compressed is True
    assert result.context_result.summarized_message_count == 4
    assert [item["content"] for item in client.calls[0][-3:]] == [
        "history question 10",
        "history answer 10",
        "current",
    ]
    assert store.count_messages("user", "window") == 22


def test_context_error_skips_runtime_and_database_write(store: SQLiteStore) -> None:
    store.create_session("user", "window")
    seed_exchanges(store, "user", "window", 1)
    failing = FailingContextManager()
    service, client, _ = make_service(
        store,
        [final_content()],
        context_manager=failing,
    )

    with pytest.raises(ContextCompressionError, match="invalid"):
        service.chat("user", "window", "new question")

    assert client.calls == []
    assert store.count_messages("user", "window") == 2


@pytest.mark.parametrize(
    ("responses", "max_steps", "expected"),
    [
        ([LLMRequestError("offline")], 8, AgentLLMError),
        (["not-json"], 8, AgentDecisionError),
        ([tool_content("todo", {"action": "list"})], 1, AgentMaxStepsError),
    ],
)
def test_runtime_errors_still_do_not_save_exchange(
    store: SQLiteStore,
    responses: List[FakeResponse],
    max_steps: int,
    expected: type[Exception],
) -> None:
    store.create_session("user", "window")
    seed_exchanges(store, "user", "window", 1)
    service, _, _ = make_service(store, responses, max_steps=max_steps)

    with pytest.raises(expected):
        service.chat("user", "window", "new")

    assert store.count_messages("user", "window") == 2


def test_result_properties_and_to_dict_expose_only_compact_context_stats(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    seed_exchanges(store, "user", "window", 3)
    service, _, _ = make_service(
        store,
        [final_content()],
        config=compression_config(),
    )
    result = service.chat("user", "window", "current")

    value = result.to_dict()
    context = value["context"]
    assert result.context_compressed is True
    assert result.context_message_count == result.context_result.output_message_count
    assert context == result.assistant_message.metadata["context"]
    assert "messages" not in context
    assert "summary_text" not in context
    json.dumps(value, ensure_ascii=False)

    legacy = replace(result, context_result=None)
    assert legacy.context_compressed is False
    assert legacy.context_message_count == legacy.loaded_history_count
    assert legacy.to_dict()["context"]["compressed"] is False


def test_demo_seed_has_required_facts_and_reset_protects_agent_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    demo_database = data_directory / "context-demo.db"
    protected_database = data_directory / "agent.db"
    for path in (
        demo_database,
        Path("{}-shm".format(demo_database)),
        Path("{}-wal".format(demo_database)),
        protected_database,
    ):
        path.write_text("test", encoding="utf-8")
    monkeypatch.setattr(context_compression_demo, "DEMO_DB_PATH", demo_database)

    context_compression_demo._reset_demo_database()

    assert not demo_database.exists()
    assert not Path("{}-shm".format(demo_database)).exists()
    assert not Path("{}-wal".format(demo_database)).exists()
    assert protected_database.exists()

    store = SQLiteStore(demo_database)
    store.create_session(
        context_compression_demo.DEMO_USER_ID,
        context_compression_demo.DEMO_SESSION_ID,
    )
    context_compression_demo._seed_demo_history(store)
    contents = [
        item.content
        for item in store.list_messages(
            context_compression_demo.DEMO_USER_ID,
            context_compression_demo.DEMO_SESSION_ID,
        )
    ]
    assert len(contents) == 24
    assert any("东京" in content for content in contents)
    assert any("Atlas" in content for content in contents)
    assert any("完成 README" in content for content in contents[-2:])

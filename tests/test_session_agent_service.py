"""Offline tests for persisted Session history and Agent Runtime integration."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Union

import pytest

from app.agent import (
    AgentDecisionError,
    AgentLLMError,
    AgentMaxStepsError,
    AgentRuntime,
    SessionAgentService,
    SessionChatResult,
)
from app.llm import LLMConfig, LLMRequestError, LLMResponse
from app.memory import MemoryStoreError, SessionNotFoundError, SQLiteStore
from app.tools import ToolContext, create_default_registry
from scripts import session_memory_demo


FakeResponse = Union[str, Exception]


def final_content(
    answer: str = "最终回答",
    reasoning_summary: str = "可以直接回答。",
) -> str:
    return json.dumps(
        {
            "type": "final",
            "reasoning_summary": reasoning_summary,
            "answer": answer,
        },
        ensure_ascii=False,
    )


def tool_content(
    name: str,
    arguments: Dict[str, object],
    call_id: str = "call_1",
    reasoning_summary: str = "需要调用工具。",
) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "reasoning_summary": reasoning_summary,
            "tool_calls": [
                {"id": call_id, "name": name, "arguments": arguments}
            ],
        },
        ensure_ascii=False,
    )


class FakeLLMClient:
    """Return fixed responses and retain snapshots of every LLM call."""

    def __init__(
        self,
        responses: List[FakeResponse],
        config: Optional[LLMConfig] = None,
    ) -> None:
        self.responses = list(responses)
        self.calls: List[List[Dict[str, str]]] = []
        self.config = config
        self.closed = False

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])
        if not self.responses:
            raise RuntimeError("Fake response list is exhausted.")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(content=response, model="fake-model")

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "session-service" / "agent.db")


def make_service(
    store: SQLiteStore,
    responses: List[FakeResponse],
    history_limit: Optional[int] = None,
    max_steps: int = 8,
    config: Optional[LLMConfig] = None,
) -> tuple[SessionAgentService, FakeLLMClient, AgentRuntime]:
    client = FakeLLMClient(responses, config=config)
    runtime = AgentRuntime(  # type: ignore[arg-type]
        llm_client=client,
        tool_registry=create_default_registry(todo_store=store),
        max_steps=max_steps,
    )
    return (
        SessionAgentService(runtime, store, history_limit=history_limit),
        client,
        runtime,
    )


def test_initialization_accepts_none_and_positive_history_limit(
    store: SQLiteStore,
) -> None:
    none_service, none_client, runtime = make_service(store, [final_content()])
    limited_service = SessionAgentService(runtime, store, history_limit=3)

    assert none_service.history_limit is None
    assert limited_service.history_limit == 3
    assert none_client.calls == []
    assert store.list_sessions("user") == []


def test_initialization_rejects_invalid_runtime(store: SQLiteStore) -> None:
    with pytest.raises(ValueError, match="AgentRuntime"):
        SessionAgentService(object(), store)  # type: ignore[arg-type]


def test_initialization_rejects_invalid_store(store: SQLiteStore) -> None:
    _, _, runtime = make_service(store, [final_content()])

    with pytest.raises(ValueError, match="SQLiteStore"):
        SessionAgentService(runtime, object())  # type: ignore[arg-type]


@pytest.mark.parametrize("history_limit", [0, -1, True, 1.5, "2"])
def test_initialization_rejects_invalid_history_limit(
    store: SQLiteStore,
    history_limit: object,
) -> None:
    _, _, runtime = make_service(store, [final_content()])

    with pytest.raises(ValueError, match="history_limit"):
        SessionAgentService(  # type: ignore[arg-type]
            runtime,
            store,
            history_limit=history_limit,
        )


@pytest.mark.parametrize(
    ("user_id", "session_id", "user_input", "field_name"),
    [
        (" ", "session", "hello", "user_id"),
        ("user", " ", "hello", "session_id"),
        ("user", "session", " ", "user_input"),
    ],
)
def test_chat_rejects_empty_input(
    store: SQLiteStore,
    user_id: str,
    session_id: str,
    user_input: str,
    field_name: str,
) -> None:
    service, client, _ = make_service(store, [final_content()])

    with pytest.raises(ValueError, match=field_name):
        service.chat(user_id, session_id, user_input)

    assert client.calls == []


def test_missing_session_fails_without_creating_it(store: SQLiteStore) -> None:
    service, client, _ = make_service(store, [final_content()])

    with pytest.raises(SessionNotFoundError, match="does not exist"):
        service.chat("user", "missing", "hello")

    assert store.get_session("user", "missing") is None
    assert store.count_messages("user", "missing") == 0
    assert client.calls == []


def test_first_chat_loads_no_history_and_persists_exactly_two_messages(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window", "Window")
    service, client, _ = make_service(store, [final_content("你好！")])

    result = service.chat("user", "window", "你好")
    messages = store.list_messages("user", "window")

    assert result.loaded_history_count == 0
    assert [message["role"] for message in client.calls[0]] == ["system", "user"]
    assert client.calls[0][-1]["content"] == "你好"
    assert len(messages) == 2
    assert [message.role for message in messages] == ["user", "assistant"]
    assert [message.content for message in messages] == ["你好", "你好！"]
    assert result.user_message.id == messages[0].id
    assert result.assistant_message.id == messages[1].id


def test_assistant_metadata_is_compact_and_secret_free(store: SQLiteStore) -> None:
    secret = "session-service-secret-key"
    store.create_session("user", "window")
    service, _, _ = make_service(
        store,
        [final_content("回答", "reason mentions {}".format(secret))],
        config=LLMConfig(secret, "https://llm.invalid/v1", "fake-model"),
    )

    result = service.chat("user", "window", "问题")
    metadata = result.assistant_message.metadata
    serialized = json.dumps(metadata, ensure_ascii=False).lower()

    assert metadata == {
        "agent": {
            "total_llm_calls": 1,
            "total_tool_calls": 0,
            "stopped_reason": "final",
            "used_tools": [],
            "reasoning_summaries": ["reason mentions [REDACTED]"],
        }
    }
    assert secret not in serialized
    assert "system_prompt" not in serialized
    assert "authorization" not in serialized
    assert '"messages"' not in serialized


def test_second_chat_receives_only_prior_natural_language_messages(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    service, client, _ = make_service(
        store,
        [final_content("第一答"), final_content("第二答")],
    )

    service.chat("user", "window", "第一问")
    second = service.chat("user", "window", "第二问")
    second_call = client.calls[1]

    assert second.loaded_history_count == 2
    assert [message["role"] for message in second_call] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
    assert [message["content"] for message in second_call[1:]] == [
        "第一问",
        "第一答",
        "第二问",
    ]
    assert sum(message["role"] == "system" for message in second_call) == 1
    assert [message.role for message in store.list_messages("user", "window")] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_tool_turn_persists_only_user_and_final_answer(store: SQLiteStore) -> None:
    store.create_session("user", "window")
    service, client, _ = make_service(
        store,
        [
            tool_content(
                "calculator",
                {"expression": "12 * (3 + 2)"},
                reasoning_summary="需要调用计算器。",
            ),
            final_content("结果是 60。", "已有结果，可以回答。"),
            final_content("刚才结果是 60。"),
        ],
    )

    first = service.chat("user", "window", "请计算")
    second = service.chat("user", "window", "刚才结果是什么？")
    persisted = store.list_messages("user", "window")
    next_context = client.calls[2]

    assert first.agent_result.total_llm_calls == 2
    assert first.agent_result.total_tool_calls == 1
    assert [message.content for message in persisted[:2]] == ["请计算", "结果是 60。"]
    assert len(persisted) == 4
    assert first.assistant_message.metadata["agent"]["used_tools"] == ["calculator"]
    assert first.assistant_message.metadata["agent"]["reasoning_summaries"] == [
        "需要调用计算器。",
        "已有结果，可以回答。",
    ]
    assert second.loaded_history_count == 2
    serialized_context = json.dumps(next_context, ensure_ascii=False)
    assert "tool_call_id" not in serialized_context
    assert "Tool execution result" not in serialized_context
    assert "结果是 60。" in serialized_context


def test_used_tools_preserves_first_seen_order_without_duplicates(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    client = FakeLLMClient(
        [
            json.dumps(
                {
                    "type": "tool_call",
                    "reasoning_summary": "需要多个工具。",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "name": "search",
                            "arguments": {"query": "FastAPI"},
                        },
                        {
                            "id": "c2",
                            "name": "calculator",
                            "arguments": {"expression": "1 + 1"},
                        },
                        {
                            "id": "c3",
                            "name": "search",
                            "arguments": {"query": "Python"},
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            final_content("完成"),
        ]
    )
    runtime = AgentRuntime(  # type: ignore[arg-type]
        client,
        create_default_registry(todo_store=store),
    )
    service = SessionAgentService(runtime, store)

    result = service.chat("user", "window", "处理")

    assert result.assistant_message.metadata["agent"]["used_tools"] == [
        "search",
        "calculator",
    ]


def test_persistent_todo_uses_each_session_tool_context(store: SQLiteStore) -> None:
    for session_id in ["window-1", "window-2"]:
        store.create_session("user", session_id)
    service, _, _ = make_service(
        store,
        [
            tool_content("todo", {"action": "add", "content": "窗口一"}, "w1-add"),
            final_content("已添加窗口一待办"),
            tool_content("todo", {"action": "add", "content": "窗口二"}, "w2-add"),
            final_content("已添加窗口二待办"),
            tool_content("todo", {"action": "list"}, "w1-list"),
            final_content("窗口一只有窗口一待办"),
            tool_content("todo", {"action": "list"}, "w2-list"),
            final_content("窗口二只有窗口二待办"),
        ],
    )

    service.chat("user", "window-1", "添加窗口一")
    service.chat("user", "window-2", "添加窗口二")
    first_list = service.chat("user", "window-1", "列出待办")
    second_list = service.chat("user", "window-2", "列出待办")

    assert [todo.content for todo in store.list_todos("user", "window-1")] == [
        "窗口一"
    ]
    assert [todo.content for todo in store.list_todos("user", "window-2")] == [
        "窗口二"
    ]
    assert "窗口一" in json.dumps(first_list.agent_result.to_dict(), ensure_ascii=False)
    assert "窗口二" in json.dumps(second_list.agent_result.to_dict(), ensure_ascii=False)


def test_session_windows_are_isolated_and_clear_keeps_todos(
    store: SQLiteStore,
) -> None:
    for session_id in ["window-1", "window-2"]:
        store.create_session("user", session_id)
    store.add_todo("user", "window-1", "keep me")
    service, client, _ = make_service(
        store,
        [
            final_content("answer one"),
            final_content("answer two"),
            final_content("follow one"),
        ],
    )

    service.chat("user", "window-1", "question one")
    service.chat("user", "window-2", "question two")
    service.chat("user", "window-1", "follow-up one")

    third_context = json.dumps(client.calls[2], ensure_ascii=False)
    assert "question one" in third_context
    assert "question two" not in third_context
    assert service.clear_history("user", "window-1") == 4
    assert service.get_history("user", "window-1") == []
    assert len(service.get_history("user", "window-2")) == 2
    assert store.list_todos("user", "window-1")[0].content == "keep me"
    assert store.get_session("user", "window-1") is not None


def test_users_with_same_session_id_are_isolated(store: SQLiteStore) -> None:
    for user_id in ["user-a", "user-b"]:
        store.create_session(user_id, "same")
    service, client, _ = make_service(
        store,
        [
            final_content("answer a"),
            final_content("answer b"),
            final_content("follow b"),
        ],
    )

    service.chat("user-a", "same", "private a")
    service.chat("user-b", "same", "private b")
    service.chat("user-b", "same", "follow b")

    assert [message.content for message in service.get_history("user-a", "same")] == [
        "private a",
        "answer a",
    ]
    assert "private a" not in json.dumps(client.calls[2], ensure_ascii=False)
    assert "private b" in json.dumps(client.calls[2], ensure_ascii=False)


def test_recreated_service_loads_messages_and_todos(store: SQLiteStore) -> None:
    store.create_session("user", "window")
    first_service, _, _ = make_service(
        store,
        [
            tool_content("todo", {"action": "add", "content": "persistent"}),
            final_content("已保存"),
        ],
    )
    first_service.chat("user", "window", "保存待办")

    reopened_store = SQLiteStore(store.db_path)
    second_service, second_client, _ = make_service(
        reopened_store,
        [final_content("仍然记得")],
    )
    result = second_service.chat("user", "window", "你还记得吗？")

    assert result.loaded_history_count == 2
    assert [message["content"] for message in second_client.calls[0][1:]] == [
        "保存待办",
        "已保存",
        "你还记得吗？",
    ]
    assert reopened_store.list_todos("user", "window")[0].content == "persistent"
    assert [message.role for message in second_service.get_history("user", "window")] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]


def test_history_limit_loads_recent_messages_without_deleting_history(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    for index in range(1, 4):
        store.add_exchange(
            "user",
            "window",
            "question {}".format(index),
            "answer {}".format(index),
        )
    service, client, _ = make_service(
        store,
        [final_content("answer 4")],
        history_limit=2,
    )

    result = service.chat("user", "window", "question 4")

    assert result.loaded_history_count == 2
    assert [message["content"] for message in client.calls[0][1:]] == [
        "question 3",
        "answer 3",
        "question 4",
    ]
    assert store.count_messages("user", "window") == 8


@pytest.mark.parametrize(
    ("responses", "max_steps", "expected_error"),
    [
        ([LLMRequestError("offline")], 8, AgentLLMError),
        (["not json"], 8, AgentDecisionError),
        (
            [tool_content("calculator", {"expression": "1 + 1"})],
            1,
            AgentMaxStepsError,
        ),
    ],
)
def test_runtime_failure_does_not_persist_partial_messages(
    store: SQLiteStore,
    responses: List[FakeResponse],
    max_steps: int,
    expected_error: type[Exception],
) -> None:
    store.create_session("user", "window")
    store.add_exchange("user", "window", "old question", "old answer")
    service, _, _ = make_service(store, responses, max_steps=max_steps)

    with pytest.raises(expected_error):
        service.chat("user", "window", "new question")

    assert [message.content for message in store.list_messages("user", "window")] == [
        "old question",
        "old answer",
    ]


def test_add_exchange_rolls_back_user_when_assistant_insert_fails(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    with sqlite3.connect(str(store.db_path)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_assistant_insert
            BEFORE INSERT ON messages
            WHEN NEW.role = 'assistant'
            BEGIN
                SELECT RAISE(ABORT, 'assistant insert failed');
            END;
            """
        )

    with pytest.raises(MemoryStoreError, match="exchange"):
        store.add_exchange("user", "window", "question", "answer")

    assert store.count_messages("user", "window") == 0


def test_add_exchange_returns_consecutive_records_and_updates_session(
    store: SQLiteStore,
) -> None:
    original = store.create_session("user", "window")

    user_message, assistant_message = store.add_exchange(
        "user",
        "window",
        "question",
        "answer",
        {"agent": {"total_llm_calls": 1}},
    )
    updated = store.get_session("user", "window")

    assert assistant_message.id == user_message.id + 1
    assert [user_message.role, assistant_message.role] == ["user", "assistant"]
    assert assistant_message.metadata == {"agent": {"total_llm_calls": 1}}
    assert updated is not None
    assert updated.updated_at >= original.updated_at
    assert [message.id for message in store.list_messages("user", "window")] == [
        user_message.id,
        assistant_message.id,
    ]


@pytest.mark.parametrize(
    ("user_content", "assistant_content"),
    [(" ", "answer"), ("question", " ")],
)
def test_add_exchange_validates_both_contents(
    store: SQLiteStore,
    user_content: str,
    assistant_content: str,
) -> None:
    store.create_session("user", "window")

    with pytest.raises(ValueError, match="content"):
        store.add_exchange("user", "window", user_content, assistant_content)

    assert store.count_messages("user", "window") == 0


def test_add_exchange_validates_metadata_and_existing_session(
    store: SQLiteStore,
) -> None:
    with pytest.raises(SessionNotFoundError):
        store.add_exchange("user", "missing", "question", "answer")

    store.create_session("user", "window")
    with pytest.raises(ValueError, match="metadata"):
        store.add_exchange(  # type: ignore[arg-type]
            "user",
            "window",
            "question",
            "answer",
            {"invalid": object()},
        )


def test_get_history_validates_limit_and_requires_session(store: SQLiteStore) -> None:
    store.create_session("user", "window")
    store.add_exchange("user", "window", "q1", "a1")
    store.add_exchange("user", "window", "q2", "a2")
    service, _, _ = make_service(store, [final_content()])

    assert [message.content for message in service.get_history("user", "window", 2)] == [
        "q2",
        "a2",
    ]
    with pytest.raises(ValueError, match="limit"):
        service.get_history("user", "window", True)
    with pytest.raises(SessionNotFoundError):
        service.get_history("user", "missing")
    with pytest.raises(SessionNotFoundError):
        service.clear_history("user", "missing")


def test_session_chat_result_to_dict_and_latest_session(store: SQLiteStore) -> None:
    original = store.create_session("user", "window", "Title")
    service, _, _ = make_service(store, [final_content("answer")])

    result = service.chat("user", "window", "question")
    result_dict = result.to_dict()

    assert isinstance(result, SessionChatResult)
    assert result.session.updated_at >= original.updated_at
    assert result_dict["session"] == result.session.to_dict()
    assert result_dict["user_message"] == result.user_message.to_dict()
    assert result_dict["assistant_message"] == result.assistant_message.to_dict()
    assert result_dict["agent_result"] == result.agent_result.to_dict()
    assert result_dict["loaded_history_count"] == 0


def test_demo_reset_removes_only_explicit_demo_database_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    demo_database = data_directory / "session-demo.db"
    demo_shm = Path("{}-shm".format(demo_database))
    demo_wal = Path("{}-wal".format(demo_database))
    protected_database = data_directory / "agent.db"
    for path in [demo_database, demo_shm, demo_wal, protected_database]:
        path.write_text("test", encoding="utf-8")
    monkeypatch.setattr(session_memory_demo, "DEMO_DB_PATH", demo_database)

    session_memory_demo._reset_demo_database()

    assert not demo_database.exists()
    assert not demo_shm.exists()
    assert not demo_wal.exists()
    assert protected_database.exists()

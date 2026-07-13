"""Offline tests for automatic Trace recording by SessionAgentService."""

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
)
from app.llm import LLMRequestError, LLMResponse
from app.memory import (
    BasicContextManager,
    ContextCompressionError,
    ContextConfig,
    MemoryStoreError,
    SQLiteStore,
)
from app.observability import SQLiteTraceRecorder, TracePersistenceError
from app.tools import create_default_registry


FakeResponse = Union[str, Exception]


def final_content(
    answer: str = "最终回答",
    reasoning_summary: str = "可以回答。",
) -> str:
    return json.dumps(
        {
            "type": "final",
            "reasoning_summary": reasoning_summary,
            "answer": answer,
        },
        ensure_ascii=False,
    )


def tool_content(calls: List[Dict[str, object]]) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "reasoning_summary": "需要调用工具。",
            "tool_calls": calls,
        },
        ensure_ascii=False,
    )


class FakeLLMClient:
    def __init__(self, responses: List[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: List[List[Dict[str, str]]] = []

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(content=response, model="fake-model")


class FailingContextManager(BasicContextManager):
    def build(self, history):  # type: ignore[no-untyped-def]
        raise ContextCompressionError("Context could not be built.")


class FailingTraceRecorder(SQLiteTraceRecorder):
    def record_context(self, run_id, context_result):  # type: ignore[no-untyped-def]
        raise TracePersistenceError("Trace event could not be written.")


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "session-trace" / "agent.db")


def make_service(
    store: SQLiteStore,
    responses: List[FakeResponse],
    max_steps: int = 8,
    context_manager: Optional[BasicContextManager] = None,
    trace_recorder: Optional[SQLiteTraceRecorder] = None,
):
    client = FakeLLMClient(responses)
    runtime = AgentRuntime(  # type: ignore[arg-type]
        client,
        create_default_registry(todo_store=store),
        max_steps=max_steps,
    )
    service = SessionAgentService(
        runtime,
        store,
        context_manager=context_manager,
        trace_recorder=trace_recorder,
    )
    return service, client


def seed(store: SQLiteStore, user_id: str, session_id: str, turns: int) -> None:
    for index in range(turns):
        store.add_exchange(
            user_id,
            session_id,
            "question {}".format(index),
            "answer {}".format(index),
        )


def test_default_recorder_is_enabled_and_invalid_injection_fails(
    store: SQLiteStore,
) -> None:
    client = FakeLLMClient([final_content()])
    runtime = AgentRuntime(client, create_default_registry())  # type: ignore[arg-type]
    service = SessionAgentService(runtime, store)
    assert isinstance(service.trace_recorder, SQLiteTraceRecorder)
    with pytest.raises(TypeError, match="trace_recorder"):
        SessionAgentService(runtime, store, trace_recorder=object())  # type: ignore[arg-type]


def test_successful_direct_chat_returns_completed_run_and_context_event(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    service, _ = make_service(store, [final_content("answer")])

    result = service.chat("user", "window", "question")
    trace = service.trace_recorder.get_trace(result.run_id)

    assert result.run_id
    assert result.to_dict()["run_id"] == result.run_id
    assert trace.run.status == "completed"
    assert trace.run.final_answer == "answer"
    assert trace.run.total_llm_calls == 1
    assert trace.run.total_tool_calls == 0
    assert [event.event_type for event in trace.events] == [
        "run_started",
        "context_built",
        "llm_decision",
        "run_completed",
    ]
    assert trace.events[1].payload["compressed"] is False
    assert store.count_messages("user", "window") == 2


def test_compressed_context_statistics_are_traced_without_summary(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    seed(store, "user", "window", 3)
    manager = BasicContextManager(
        ContextConfig(
            max_messages=4,
            recent_messages=2,
            max_chars=1000,
            summary_max_chars=400,
            per_message_chars=100,
        )
    )
    service, _ = make_service(
        store,
        [final_content()],
        context_manager=manager,
    )

    result = service.chat("user", "window", "current")
    event = next(
        item
        for item in service.trace_recorder.get_trace(result.run_id).events
        if item.event_type == "context_built"
    )
    serialized = json.dumps(event.to_dict(), ensure_ascii=False)

    assert event.payload["compressed"] is True
    assert event.payload["original_message_count"] == 6
    assert event.payload["summarized_message_count"] == 4
    assert "summary_text" not in serialized
    assert '"messages"' not in serialized


def test_calculator_loop_records_real_result_and_only_final_exchange(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    service, _ = make_service(
        store,
        [
            tool_content(
                [
                    {
                        "id": "calc",
                        "name": "calculator",
                        "arguments": {"expression": "12 * (3 + 2)"},
                    }
                ]
            ),
            final_content("60"),
        ],
    )

    result = service.chat("user", "window", "calculate")
    trace = service.trace_recorder.get_trace(result.run_id)
    tool_result = next(
        item for item in trace.events if item.event_type == "tool_result"
    )

    assert trace.run.total_llm_calls == 2
    assert trace.run.total_tool_calls == 1
    assert tool_result.payload["tool_name"] == "calculator"
    assert tool_result.payload["output"]["result"] == 60
    assert [item.content for item in store.list_messages("user", "window")] == [
        "calculate",
        "60",
    ]


def test_search_and_todo_trace_order_and_persistent_scope(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    service, _ = make_service(
        store,
        [
            tool_content(
                [
                    {
                        "id": "search",
                        "name": "search",
                        "arguments": {"query": "Python"},
                    },
                    {
                        "id": "todo",
                        "name": "todo",
                        "arguments": {"action": "add", "content": "检查结果"},
                    },
                ]
            ),
            final_content("done"),
        ],
    )

    result = service.chat("user", "window", "search and save")
    events = service.trace_recorder.get_trace(result.run_id).events
    tools = [
        (item.event_type, item.payload["tool_name"])
        for item in events
        if item.event_type in {"tool_call", "tool_result"}
    ]

    assert tools == [
        ("tool_call", "search"),
        ("tool_result", "search"),
        ("tool_call", "todo"),
        ("tool_result", "todo"),
    ]
    todo = store.list_todos("user", "window")[0]
    assert (todo.user_id, todo.session_id, todo.content) == (
        "user",
        "window",
        "检查结果",
    )


def test_trace_isolated_between_sessions_and_users(store: SQLiteStore) -> None:
    for user_id, session_id in (
        ("user-a", "same"),
        ("user-b", "same"),
        ("user-a", "other"),
    ):
        store.create_session(user_id, session_id)
    service, _ = make_service(
        store,
        [final_content("a"), final_content("b"), final_content("other")],
    )
    first = service.chat("user-a", "same", "private a")
    second = service.chat("user-b", "same", "private b")
    third = service.chat("user-a", "other", "private other")

    user_a_same = service.trace_recorder.list_runs("user-a", session_id="same")
    user_b_same = service.trace_recorder.list_runs("user-b", session_id="same")
    user_a_other = service.trace_recorder.list_runs("user-a", session_id="other")

    assert [item.run_id for item in user_a_same] == [first.run_id]
    assert [item.run_id for item in user_b_same] == [second.run_id]
    assert [item.run_id for item in user_a_other] == [third.run_id]


@pytest.mark.parametrize(
    ("responses", "max_steps", "manager", "expected", "error_type"),
    [
        ([], 8, FailingContextManager(), ContextCompressionError, "ContextCompressionError"),
        ([LLMRequestError("offline")], 8, None, AgentLLMError, "AgentLLMError"),
        (["not json"], 8, None, AgentDecisionError, "AgentDecisionError"),
        (
            [
                tool_content(
                    [
                        {
                            "id": "todo",
                            "name": "todo",
                            "arguments": {"action": "list"},
                        }
                    ]
                )
            ],
            1,
            None,
            AgentMaxStepsError,
            "AgentMaxStepsError",
        ),
    ],
)
def test_failures_create_failed_run_without_saving_messages(
    store: SQLiteStore,
    responses: List[FakeResponse],
    max_steps: int,
    manager: Optional[BasicContextManager],
    expected: type[Exception],
    error_type: str,
) -> None:
    store.create_session("user", "window")
    service, _ = make_service(
        store,
        responses,
        max_steps=max_steps,
        context_manager=manager,
    )

    with pytest.raises(expected):
        service.chat("user", "window", "question")

    runs = service.trace_recorder.list_runs("user", status="failed")
    assert len(runs) == 1
    assert runs[0].error_type == error_type
    assert runs[0].finished_at is not None
    assert store.count_messages("user", "window") == 0
    assert service.trace_recorder.get_trace(runs[0].run_id).events[-1].event_type == (
        "run_failed"
    )


def test_trace_data_and_reasoning_summary_do_not_enter_next_context(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    service, client = make_service(
        store,
        [
            final_content("first answer", "trace-only reasoning"),
            final_content("second answer"),
        ],
    )
    first = service.chat("user", "window", "first question")
    service.chat("user", "window", "second question")
    next_history = json.dumps(client.calls[1][1:-1], ensure_ascii=False)
    trace_json = json.dumps(
        service.trace_recorder.get_trace(first.run_id).to_dict(),
        ensure_ascii=False,
    )

    assert "trace-only reasoning" in trace_json
    assert "trace-only reasoning" not in next_history
    assert first.run_id not in next_history
    assert "run_started" not in next_history
    assert "first question" in next_history
    assert "first answer" in next_history


def test_trace_write_failure_is_raised_and_not_presented_as_success(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    recorder = FailingTraceRecorder(store)
    service, client = make_service(
        store,
        [final_content()],
        trace_recorder=recorder,
    )

    with pytest.raises(TracePersistenceError, match="could not be written"):
        service.chat("user", "window", "question")

    assert client.calls == []
    assert store.count_messages("user", "window") == 0
    failed = recorder.list_runs("user", status="failed")
    assert len(failed) == 1
    assert failed[0].error_type == "TracePersistenceError"


def test_message_persistence_failure_rolls_back_exchange_and_fails_trace(
    store: SQLiteStore,
) -> None:
    store.create_session("user", "window")
    with sqlite3.connect(str(store.db_path)) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_trace_test_assistant
            BEFORE INSERT ON messages
            WHEN NEW.role = 'assistant'
            BEGIN
                SELECT RAISE(ABORT, 'assistant insert failed');
            END;
            """
        )
    service, _ = make_service(store, [final_content()])

    with pytest.raises(MemoryStoreError, match="exchange"):
        service.chat("user", "window", "question")

    assert store.count_messages("user", "window") == 0
    failed = service.trace_recorder.list_runs("user", status="failed")
    assert len(failed) == 1
    assert failed[0].error_type == "MemoryStoreError"
    assert service.trace_recorder.get_trace(failed[0].run_id).events[-1].event_type == (
        "run_failed"
    )

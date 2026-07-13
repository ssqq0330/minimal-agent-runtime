"""Tests for sanitized SQLite Agent Trace persistence."""

from __future__ import annotations

import copy
import json
import sqlite3
from pathlib import Path
from typing import Dict, List

import pytest

from app.agent import AgentRuntime
from app.llm import LLMResponse
from app.memory import BasicContextManager, ContextConfig, SQLiteStore
from app.observability import (
    SQLiteTraceRecorder,
    TraceNotFoundError,
    TraceValidationError,
    sanitize_trace_payload,
)
from app.tools import ToolContext, create_default_registry
from scripts import trace_demo


def decision_final(answer: str = "完成") -> str:
    return json.dumps(
        {
            "type": "final",
            "reasoning_summary": "已有结果，可以回答。",
            "answer": answer,
        },
        ensure_ascii=False,
    )


def decision_tools(calls: List[Dict[str, object]]) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "reasoning_summary": "需要调用工具。",
            "tool_calls": calls,
        },
        ensure_ascii=False,
    )


class FakeLLMClient:
    def __init__(self, responses: List[str]) -> None:
        self.responses = list(responses)

    def complete(self, messages):  # type: ignore[no-untyped-def]
        return LLMResponse(content=self.responses.pop(0), model="fake-model")


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    value = SQLiteStore(tmp_path / "trace" / "agent.db")
    value.create_session("user-a", "window-1")
    value.create_session("user-a", "window-2")
    value.create_session("user-b", "window-1")
    return value


@pytest.fixture
def recorder(store: SQLiteStore) -> SQLiteTraceRecorder:
    return SQLiteTraceRecorder(store)


def run_agent(responses: List[str]):
    runtime = AgentRuntime(  # type: ignore[arg-type]
        FakeLLMClient(responses),
        create_default_registry(),
    )
    return runtime.run("execute", ToolContext("user-a", "window-1"))


def test_schema_is_created_with_expected_trace_tables(store: SQLiteStore) -> None:
    with sqlite3.connect(str(store.db_path)) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert {"agent_runs", "trace_events"} <= tables
    assert {
        "idx_agent_runs_session_started",
        "idx_agent_runs_status_started",
        "idx_trace_events_run_sequence",
    } <= indexes


def test_recorder_initialization_has_no_run_and_validates_store(
    store: SQLiteStore,
) -> None:
    recorder = SQLiteTraceRecorder(store)
    assert recorder.list_runs("user-a") == []
    with pytest.raises(TypeError, match="SQLiteStore"):
        SQLiteTraceRecorder(object())  # type: ignore[arg-type]


def test_start_run_is_unique_running_and_creates_first_event(
    recorder: SQLiteTraceRecorder,
) -> None:
    first = recorder.start_run("user-a", "window-1", "hello")
    second = recorder.start_run("user-a", "window-1", "hello again")
    trace = recorder.get_trace(first.run_id)

    assert first.status == "running"
    assert first.run_id != second.run_id
    assert first.finished_at is None
    assert [event.event_type for event in trace.events] == ["run_started"]
    assert trace.events[0].sequence == 1


def test_start_run_requires_existing_session_and_bounds_input(
    recorder: SQLiteTraceRecorder,
) -> None:
    with pytest.raises(TraceValidationError, match="Session"):
        recorder.start_run("user-a", "missing", "hello")
    run = recorder.start_run("user-a", "window-1", "X" * 9000)
    assert len(run.user_input) <= 8000
    assert "trace 已截断" in run.user_input


def test_context_event_contains_only_statistics(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "hello")
    manager = BasicContextManager(
        ContextConfig(
            max_messages=2,
            recent_messages=1,
            max_chars=300,
            summary_max_chars=120,
            per_message_chars=60,
        )
    )
    context = manager.build(
        [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "recent"},
        ]
    )

    event = recorder.record_context(run.run_id, context)

    assert event.event_type == "context_built"
    assert event.payload == {
        "compressed": True,
        "original_message_count": 3,
        "output_message_count": 2,
        "summarized_message_count": 2,
        "retained_recent_count": 1,
        "original_char_count": context.original_char_count,
        "output_char_count": context.output_char_count,
    }
    serialized = json.dumps(event.to_dict(), ensure_ascii=False)
    assert "summary_text" not in serialized
    assert '"messages"' not in serialized


def test_direct_final_records_decision_completion_and_run_totals(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "hello")
    result = run_agent([decision_final("answer")])

    completed = recorder.record_agent_result(run.run_id, result)
    trace = recorder.get_trace(run.run_id)

    assert completed.status == "completed"
    assert completed.final_answer == "answer"
    assert completed.total_llm_calls == 1
    assert completed.total_tool_calls == 0
    assert completed.finished_at is not None
    assert [event.event_type for event in trace.events] == [
        "run_started",
        "llm_decision",
        "run_completed",
    ]
    assert trace.events[1].payload == {
        "decision_type": "final",
        "reasoning_summary": "已有结果，可以回答。",
        "model": "fake-model",
    }


def test_calculator_records_real_call_and_result_in_order(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "calculate")
    result = run_agent(
        [
            decision_tools(
                [
                    {
                        "id": "calc-1",
                        "name": "calculator",
                        "arguments": {"expression": "12 * (3 + 2)"},
                    }
                ]
            ),
            decision_final("60"),
        ]
    )

    recorder.record_agent_result(run.run_id, result)
    trace = recorder.get_trace(run.run_id)
    event_types = [event.event_type for event in trace.events]
    tool_call = next(event for event in trace.events if event.event_type == "tool_call")
    tool_result = next(
        event for event in trace.events if event.event_type == "tool_result"
    )

    assert event_types == [
        "run_started",
        "llm_decision",
        "tool_call",
        "tool_result",
        "llm_decision",
        "run_completed",
    ]
    assert tool_call.payload["tool_name"] == "calculator"
    assert tool_result.payload["success"] is True
    assert tool_result.payload["output"]["result"] == 60
    assert [event.sequence for event in trace.events] == list(
        range(1, len(trace.events) + 1)
    )


def test_failed_tool_result_is_recorded_before_runtime_recovers(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "bad calculation")
    result = run_agent(
        [
            decision_tools(
                [
                    {
                        "id": "calc-bad",
                        "name": "calculator",
                        "arguments": {"expression": "1 / 0"},
                    }
                ]
            ),
            decision_final("无法除以零"),
        ]
    )
    recorder.record_agent_result(run.run_id, result)
    event = next(
        item
        for item in recorder.get_trace(run.run_id).events
        if item.event_type == "tool_result"
    )
    assert event.payload["success"] is False
    assert event.payload["output"] is None
    assert "Division by zero" in event.payload["error"]


def test_multiple_tools_and_steps_keep_call_result_pair_order(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "multiple")
    result = run_agent(
        [
            decision_tools(
                [
                    {
                        "id": "search-1",
                        "name": "search",
                        "arguments": {"query": "Python"},
                    },
                    {
                        "id": "calc-1",
                        "name": "calculator",
                        "arguments": {"expression": "3 * 4"},
                    },
                ]
            ),
            decision_tools(
                [
                    {
                        "id": "todo-1",
                        "name": "todo",
                        "arguments": {"action": "add", "content": "check"},
                    }
                ]
            ),
            decision_final(),
        ]
    )

    recorder.record_agent_result(run.run_id, result)
    events = recorder.get_trace(run.run_id).events
    tool_events = [
        (event.event_type, event.payload["tool_name"], event.step_number)
        for event in events
        if event.event_type in {"tool_call", "tool_result"}
    ]
    assert tool_events == [
        ("tool_call", "search", 1),
        ("tool_result", "search", 1),
        ("tool_call", "calculator", 1),
        ("tool_result", "calculator", 1),
        ("tool_call", "todo", 2),
        ("tool_result", "todo", 2),
    ]


def test_agent_messages_and_system_prompt_are_not_stored(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "hello")
    result = run_agent([decision_final()])
    system_prompt = result.messages[0]["content"]
    recorder.record_agent_result(run.run_id, result)
    serialized = json.dumps(recorder.get_trace(run.run_id).to_dict(), ensure_ascii=False)
    assert system_prompt not in serialized
    assert '"messages"' not in serialized
    assert "chain_of_thought" not in serialized


def test_fail_run_records_sanitized_short_error_and_rejects_repeat(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "hello")
    error = RuntimeError("authorization: Bearer abc api_key=secret " + "X" * 2000)

    failed = recorder.fail_run(run.run_id, error)
    trace = recorder.get_trace(run.run_id)

    assert failed.status == "failed"
    assert failed.error_type == "RuntimeError"
    assert failed.finished_at is not None
    assert "abc" not in failed.error_message
    assert "api_key=secret" not in failed.error_message
    assert len(failed.error_message) <= 1000
    assert trace.events[-1].event_type == "run_failed"
    with pytest.raises(TraceValidationError, match="no longer running"):
        recorder.fail_run(run.run_id, error)


def test_list_runs_filters_orders_limits_and_isolates_users(
    recorder: SQLiteTraceRecorder,
) -> None:
    first = recorder.start_run("user-a", "window-1", "first")
    recorder.fail_run(first.run_id, RuntimeError("failed"))
    second = recorder.start_run("user-a", "window-2", "second")
    recorder.record_agent_result(second.run_id, run_agent([decision_final()]))
    other = recorder.start_run("user-b", "window-1", "private")

    assert [run.run_id for run in recorder.list_runs("user-a")] == [
        second.run_id,
        first.run_id,
    ]
    assert [run.run_id for run in recorder.list_runs("user-a", status="failed")] == [
        first.run_id
    ]
    assert [
        run.run_id for run in recorder.list_runs("user-a", session_id="window-2")
    ] == [second.run_id]
    assert recorder.list_runs("user-a", limit=1)[0].run_id == second.run_id
    assert other.run_id not in [run.run_id for run in recorder.list_runs("user-a")]


@pytest.mark.parametrize("limit", [0, 201, True, 1.5, "2"])
def test_list_runs_validates_limit(
    recorder: SQLiteTraceRecorder,
    limit: object,
) -> None:
    with pytest.raises(TraceValidationError, match="limit"):
        recorder.list_runs("user-a", limit=limit)  # type: ignore[arg-type]


def test_delete_trace_is_user_scoped_and_missing_trace_fails(
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "hello")
    assert recorder.delete_trace("user-b", run.run_id) is False
    assert recorder.get_trace(run.run_id).run.user_id == "user-a"
    assert recorder.delete_trace("user-a", run.run_id) is True
    with pytest.raises(TraceNotFoundError):
        recorder.get_trace(run.run_id)


def test_trace_persists_after_reopen_and_cascades_with_session(
    store: SQLiteStore,
    recorder: SQLiteTraceRecorder,
) -> None:
    run = recorder.start_run("user-a", "window-1", "hello")
    recorder.record_agent_result(run.run_id, run_agent([decision_final()]))
    reopened = SQLiteTraceRecorder(SQLiteStore(store.db_path))
    assert reopened.get_trace(run.run_id).run.status == "completed"

    store.delete_session("user-a", "window-1")
    with pytest.raises(TraceNotFoundError):
        reopened.get_trace(run.run_id)


def test_sanitize_payload_redacts_nested_secrets_truncates_and_copies() -> None:
    original = {
        "api_key": "sk-one",
        "Authorization": "Bearer two",
        "nested": {
            "password": "three",
            "safe": [
                {"access_token": "four"},
                ("token=five", "X" * 4100),
            ],
        },
        "number": 7,
        "enabled": True,
        "none": None,
    }
    snapshot = copy.deepcopy(original)

    value = sanitize_trace_payload(original)

    assert value["api_key"] == "[REDACTED]"
    assert value["Authorization"] == "[REDACTED]"
    assert value["nested"]["password"] == "[REDACTED]"
    assert value["nested"]["safe"][0]["access_token"] == "[REDACTED]"
    assert value["nested"]["safe"][1][0] == "token=[REDACTED]"
    assert len(value["nested"]["safe"][1][1]) <= 4000
    assert "trace 已截断" in value["nested"]["safe"][1][1]
    assert original == snapshot


@pytest.mark.parametrize("key", ["secret", "refresh_token", "llm_api_key"])
def test_additional_sensitive_keys_are_redacted(key: str) -> None:
    assert sanitize_trace_payload({key: "private"})[key] == "[REDACTED]"


def test_system_http_and_hidden_reasoning_fields_are_redacted() -> None:
    value = sanitize_trace_payload(
        {
            "system_prompt": "complete prompt",
            "raw_response": {"body": "provider payload"},
            "chain_of_thought": "private reasoning",
            "reasoning_summary": "safe summary",
        }
    )
    assert value == {
        "system_prompt": "[REDACTED]",
        "raw_response": "[REDACTED]",
        "chain_of_thought": "[REDACTED]",
        "reasoning_summary": "safe summary",
    }


def test_trace_demo_reset_removes_only_its_database_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_directory = tmp_path / "data"
    data_directory.mkdir()
    demo_database = data_directory / "trace-demo.db"
    protected_database = data_directory / "agent.db"
    paths = [
        demo_database,
        Path("{}-shm".format(demo_database)),
        Path("{}-wal".format(demo_database)),
        protected_database,
    ]
    for path in paths:
        path.write_text("test", encoding="utf-8")
    monkeypatch.setattr(trace_demo, "DEMO_DB_PATH", demo_database)

    trace_demo._reset_demo_database()

    assert not demo_database.exists()
    assert not Path("{}-shm".format(demo_database)).exists()
    assert not Path("{}-wal".format(demo_database)).exists()
    assert protected_database.exists()

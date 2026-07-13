"""Offline end-to-end journeys through FastAPI, Runtime, tools, SQLite, and Trace."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.dependencies import create_degraded_services
from app.llm import LLMRequestError
from app.main import create_app
from app.memory import ContextConfig, SQLiteStore
from tests.api_helpers import final_content, make_test_services, tool_content


def chat(client: TestClient, user: str, session: str, message: str):
    return client.post(
        "/api/chat",
        json={"user_id": user, "session_id": session, "message": message},
    )


def create_session(client: TestClient, user: str, session: str, title: str):
    return client.post(
        "/api/sessions",
        json={"user_id": user, "session_id": session, "title": title},
    )


def test_two_window_tool_history_todo_trace_and_restart_journey(tmp_path: Path) -> None:
    responses = [
        tool_content(
            [
                {"id": "weather-search", "name": "search", "arguments": {"query": "东京天气"}},
                {"id": "weather-todo", "name": "todo", "arguments": {"action": "add", "content": "出门带伞"}},
            ]
        ),
        final_content("东京天气晴朗，已添加出门带伞。"),
        tool_content(
            [{"id": "report-todo", "name": "todo", "arguments": {"action": "add", "content": "周五前完成周报"}}]
        ),
        final_content("已添加周报待办。"),
        final_content("刚才查询的是东京；当前待办有出门带伞。"),
        final_content("当前待办有周五前完成周报。"),
        tool_content(
            [{"id": "calc", "name": "calculator", "arguments": {"expression": "12 * (3 + 2)"}}]
        ),
        final_content("计算结果是 60。"),
    ]
    services, fake = make_test_services(tmp_path, responses)
    client = TestClient(create_app(services))
    assert create_session(client, "acceptance", "weather-window", "Weather").status_code == 201
    assert create_session(client, "acceptance", "report-window", "Report").status_code == 201

    weather = chat(client, "acceptance", "weather-window", "查询东京天气并添加待办")
    report = chat(client, "acceptance", "report-window", "添加周报待办")
    weather_follow = chat(client, "acceptance", "weather-window", "刚才哪个城市？待办？")
    report_follow = chat(client, "acceptance", "report-window", "当前待办？")
    calculator = chat(client, "acceptance", "weather-window", "计算 12 * (3 + 2)")

    assert all(item.status_code == 200 for item in (weather, report, weather_follow, report_follow, calculator))
    assert "60" in calculator.json()["answer"]
    assert weather.json()["agent"]["total_tool_calls"] == 2
    assert calculator.json()["agent"]["total_tool_calls"] == 1
    assert weather_follow.json()["loaded_history_count"] == 2
    assert report_follow.json()["loaded_history_count"] == 2
    assert "东京" in json.dumps(fake.calls[4], ensure_ascii=False)
    assert "周报" not in json.dumps(fake.calls[4], ensure_ascii=False)
    assert "周报" in json.dumps(fake.calls[5], ensure_ascii=False)
    assert "东京" not in json.dumps(fake.calls[5], ensure_ascii=False)

    weather_messages = client.get(
        "/api/sessions/weather-window/messages", params={"user_id": "acceptance"}
    ).json()
    report_messages = client.get(
        "/api/sessions/report-window/messages", params={"user_id": "acceptance"}
    ).json()
    assert len(weather_messages) == 6
    assert len(report_messages) == 4
    weather_todos = client.get(
        "/api/sessions/weather-window/todos", params={"user_id": "acceptance"}
    ).json()
    report_todos = client.get(
        "/api/sessions/report-window/todos", params={"user_id": "acceptance"}
    ).json()
    assert [item["content"] for item in weather_todos] == ["出门带伞"]
    assert [item["content"] for item in report_todos] == ["周五前完成周报"]

    weather_runs = client.get(
        "/api/traces", params={"user_id": "acceptance", "session_id": "weather-window"}
    ).json()
    report_runs = client.get(
        "/api/traces", params={"user_id": "acceptance", "session_id": "report-window"}
    ).json()
    assert len(weather_runs) == 3
    assert len(report_runs) == 2
    run_id = weather.json()["run_id"]
    detail = client.get("/api/traces/{}".format(run_id), params={"user_id": "acceptance"}).json()
    assert detail["run"]["status"] == "completed"
    assert [event["sequence"] for event in detail["events"]] == list(
        range(1, len(detail["events"]) + 1)
    )
    assert [event["event_type"] for event in detail["events"]] == [
        "run_started", "context_built", "llm_decision", "tool_call", "tool_result",
        "tool_call", "tool_result", "llm_decision", "run_completed",
    ]

    reopened = SQLiteStore(tmp_path / "api" / "agent.db")
    assert [item.content for item in reopened.list_todos("acceptance", "weather-window")] == ["出门带伞"]
    assert [item.content for item in reopened.list_messages("acceptance", "report-window")] == [
        "添加周报待办", "已添加周报待办。", "当前待办？", "当前待办有周五前完成周报。"
    ]


def test_context_compression_is_ephemeral_and_returned_by_api(tmp_path: Path) -> None:
    services, _ = make_test_services(
        tmp_path,
        [final_content("compressed answer")],
        context_config=ContextConfig(
            max_messages=4,
            recent_messages=2,
            max_chars=1000,
            summary_max_chars=300,
            per_message_chars=100,
        ),
    )
    services.store.create_session("user", "window")
    for index in range(4):
        services.store.add_exchange("user", "window", "q{}".format(index), "a{}".format(index))
    client = TestClient(create_app(services))
    response = chat(client, "user", "window", "current")
    assert response.status_code == 200
    assert response.json()["context"]["compressed"] is True
    assert response.json()["run_id"]
    persisted = services.store.list_messages("user", "window")
    assert len(persisted) == 10
    assert all("较早会话摘要" not in item.content for item in persisted)


def test_direct_final_has_zero_tools_and_compact_trace(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [final_content("direct")])
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))
    response = chat(client, "user", "window", "no tools")
    detail = client.get(
        "/api/traces/{}".format(response.json()["run_id"]), params={"user_id": "user"}
    ).json()
    assert response.json()["agent"]["total_tool_calls"] == 0
    assert [item["event_type"] for item in detail["events"]] == [
        "run_started", "context_built", "llm_decision", "run_completed"
    ]


@pytest.mark.parametrize(
    "call",
    [
        {"id": "bad-calc", "name": "calculator", "arguments": {"expression": "1 / 0"}},
        {"id": "bad-args", "name": "calculator", "arguments": {"expression": True}},
        {"id": "unknown", "name": "not-registered", "arguments": {}},
    ],
)
def test_tool_failures_return_to_llm_without_crashing(tmp_path: Path, call) -> None:
    services, fake = make_test_services(
        tmp_path,
        [tool_content([call]), final_content("handled failure")],
    )
    services.store.create_session("user", "window")
    response = chat(TestClient(create_app(services)), "user", "window", "try tool")
    assert response.status_code == 200
    assert response.json()["answer"] == "handled failure"
    assert '"success": false' in fake.calls[1][-1]["content"]


@pytest.mark.parametrize(
    "responses,max_steps,status,code",
    [
        ([LLMRequestError("LLM_API_KEY=private")], 8, 502, "llm_request_failed"),
        (["not json"], 8, 502, "agent_response_invalid"),
        ([tool_content([{"id": "loop", "name": "search", "arguments": {"query": "Python"}}])], 1, 508, "agent_max_steps"),
    ],
)
def test_failed_chat_is_atomic_and_records_sanitized_failed_trace(
    tmp_path: Path, responses, max_steps: int, status: int, code: str
) -> None:
    services, _ = make_test_services(tmp_path, responses, max_steps=max_steps)
    services.store.create_session("user", "window")
    response = chat(TestClient(create_app(services)), "user", "window", "question")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert services.store.list_messages("user", "window") == []
    runs = services.trace_recorder.list_runs("user", session_id="window")
    assert len(runs) == 1 and runs[0].status == "failed"
    assert "private" not in json.dumps(runs[0].to_dict(), ensure_ascii=False)


def test_missing_session_duplicate_empty_and_long_inputs_have_contract_statuses(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [final_content()])
    client = TestClient(create_app(services))
    assert chat(client, "user", "missing", "hello").status_code == 404
    assert create_session(client, "user", "window", "one").status_code == 201
    assert create_session(client, "user", "window", "two").status_code == 409
    assert chat(client, "user", "window", "   ").status_code == 422
    assert chat(client, "user", "window", "x" * 8001).status_code == 422


def test_user_isolation_sql_style_and_xss_text_survive_safely(tmp_path: Path) -> None:
    injection = "Robert'); DROP TABLE sessions;--"
    xss = '<script>alert(1)</script><img src=x onerror=alert(2)><svg onload=alert(3)>'
    services, _ = make_test_services(tmp_path, [final_content(xss), final_content("b")])
    for user in ("a", "b"):
        services.store.create_session(user, "same")
    client = TestClient(create_app(services))
    first = chat(client, "a", "same", injection)
    chat(client, "b", "same", "private b")
    assert first.json()["answer"] == xss
    assert client.get("/api/sessions/same/messages", params={"user_id": "a"}).json()[0]["content"] == injection
    assert "private b" not in json.dumps(
        client.get("/api/sessions/same/messages", params={"user_id": "a"}).json()
    )
    b_run = services.trace_recorder.list_runs("b", session_id="same")[0]
    assert client.get("/api/traces/{}".format(b_run.run_id), params={"user_id": "a"}).status_code == 404
    assert client.delete("/api/traces/{}".format(b_run.run_id), params={"user_id": "a"}).status_code == 404
    assert client.delete("/api/sessions/same", params={"user_id": "a"}).status_code == 204
    assert services.store.get_session("b", "same") is not None
    with sqlite3.connect(services.store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1


def test_session_delete_cascades_messages_todos_and_traces(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [final_content("answer")])
    services.store.create_session("user", "window")
    services.store.add_todo("user", "window", "todo")
    client = TestClient(create_app(services))
    run_id = chat(client, "user", "window", "question").json()["run_id"]
    assert client.delete("/api/sessions/window", params={"user_id": "user"}).status_code == 204
    assert services.store.list_messages("user", "window") == []
    assert services.store.list_todos("user", "window") == []
    assert services.store.get_trace_run(run_id) is None


def test_degraded_app_health_is_ok_and_chat_is_503(tmp_path: Path) -> None:
    services = create_degraded_services(tmp_path / "degraded.db")
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["llm_configured"] is False
    assert chat(client, "user", "window", "hello").status_code == 503

"""Offline FastAPI tests for compact Session Agent chat responses."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.llm import LLMRequestError
from app.main import create_app
from app.memory import ContextConfig
from app.dependencies import create_degraded_services
from tests.api_helpers import final_content, make_test_services, tool_content


def post_chat(client: TestClient, user: str, session: str, message: str):
    return client.post(
        "/api/chat",
        json={"user_id": user, "session_id": session, "message": message},
    )


def test_first_direct_chat_returns_compact_answer_run_and_counts(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [final_content("你好")])
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))

    response = post_chat(client, "user", "window", "你好")
    value = response.json()

    assert response.status_code == 200
    assert value["answer"] == "你好"
    assert value["run_id"]
    assert value["loaded_history_count"] == 0
    assert value["agent"] == {
        "total_llm_calls": 1,
        "total_tool_calls": 0,
        "stopped_reason": "final",
    }
    assert value["context"]["compressed"] is False
    serialized = json.dumps(value, ensure_ascii=False)
    assert "system_prompt" not in serialized
    assert '"messages"' not in serialized
    assert "raw_response" not in serialized


def test_chat_requires_existing_session_and_non_empty_message(tmp_path: Path) -> None:
    services, client_llm = make_test_services(tmp_path, [final_content()])
    client = TestClient(create_app(services))

    missing = post_chat(client, "user", "missing", "hello")
    invalid = post_chat(client, "user", "missing", "   ")

    assert missing.status_code == 404
    assert missing.json() == {
        "error": {"code": "session_not_found", "message": "Session 不存在"}
    }
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert client_llm.calls == []


def test_calculator_chat_returns_real_sixty_and_trace_run(tmp_path: Path) -> None:
    services, _ = make_test_services(
        tmp_path,
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
            final_content("结果是 60"),
        ],
    )
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))

    response = post_chat(client, "user", "window", "计算")
    value = response.json()
    trace = services.trace_recorder.get_trace(value["run_id"])

    assert response.status_code == 200
    assert "60" in value["answer"]
    assert value["agent"]["total_llm_calls"] == 2
    assert value["agent"]["total_tool_calls"] == 1
    result_event = next(
        event for event in trace.events if event.event_type == "tool_result"
    )
    assert result_event.payload["output"]["result"] == 60


def test_search_todo_chat_uses_correct_session_scope(tmp_path: Path) -> None:
    services, _ = make_test_services(
        tmp_path,
        [
            tool_content(
                [
                    {
                        "id": "search",
                        "name": "search",
                        "arguments": {"query": "东京天气"},
                    },
                    {
                        "id": "todo",
                        "name": "todo",
                        "arguments": {"action": "add", "content": "出门带伞"},
                    },
                ]
            ),
            final_content("东京晴朗，已添加待办"),
        ],
    )
    for session_id in ("weather", "other"):
        services.store.create_session("user", session_id)
    client = TestClient(create_app(services))

    response = post_chat(client, "user", "weather", "查询并记录")

    assert response.status_code == 200
    assert [todo.content for todo in services.store.list_todos("user", "weather")] == [
        "出门带伞"
    ]
    assert services.store.list_todos("user", "other") == []
    assert response.json()["agent"]["total_tool_calls"] == 2


def test_second_chat_loads_only_its_user_session_history(tmp_path: Path) -> None:
    services, llm = make_test_services(
        tmp_path,
        [
            final_content("answer a"),
            final_content("answer b"),
            final_content("follow a"),
        ],
    )
    services.store.create_session("user-a", "same")
    services.store.create_session("user-b", "same")
    client = TestClient(create_app(services))

    post_chat(client, "user-a", "same", "private a")
    post_chat(client, "user-b", "same", "private b")
    response = post_chat(client, "user-a", "same", "follow")
    recalled = json.dumps(llm.calls[2][1:-1], ensure_ascii=False)

    assert response.json()["loaded_history_count"] == 2
    assert "private a" in recalled
    assert "answer a" in recalled
    assert "private b" not in recalled


def test_chat_returns_context_compression_stats_without_persisting_summary(
    tmp_path: Path,
) -> None:
    config = ContextConfig(
        max_messages=4,
        recent_messages=2,
        max_chars=1000,
        summary_max_chars=400,
        per_message_chars=100,
    )
    services, _ = make_test_services(
        tmp_path,
        [final_content()],
        context_config=config,
    )
    services.store.create_session("user", "window")
    for index in range(3):
        services.store.add_exchange("user", "window", "q{}".format(index), "a{}".format(index))
    client = TestClient(create_app(services))

    response = post_chat(client, "user", "window", "current")
    context = response.json()["context"]

    assert context["compressed"] is True
    assert context["original_message_count"] == 6
    assert context["summarized_message_count"] == 4
    assert services.store.count_messages("user", "window") == 8
    assert all(
        not item.content.startswith("【较早会话摘要】")
        for item in services.store.list_messages("user", "window")
    )


@pytest.mark.parametrize(
    ("responses", "max_steps", "status_code", "code"),
    [
        ([LLMRequestError("api_key=secret")], 8, 502, "llm_request_failed"),
        (["not-json"], 8, 502, "agent_response_invalid"),
        (
            [
                tool_content(
                    [
                        {
                            "id": "calc",
                            "name": "calculator",
                            "arguments": {"expression": "1 + 1"},
                        }
                    ]
                )
            ],
            1,
            508,
            "agent_max_steps",
        ),
    ],
)
def test_agent_failures_map_to_safe_http_errors_without_saving(
    tmp_path: Path,
    responses,
    max_steps: int,
    status_code: int,
    code: str,
) -> None:
    services, _ = make_test_services(
        tmp_path,
        responses,
        max_steps=max_steps,
    )
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))

    response = post_chat(client, "user", "window", "question")
    serialized = json.dumps(response.json(), ensure_ascii=False)

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code
    assert services.store.count_messages("user", "window") == 0
    assert "secret" not in serialized
    assert "Authorization" not in serialized
    assert "traceback" not in serialized.lower()


def test_missing_llm_configuration_keeps_database_but_chat_returns_503(
    tmp_path: Path,
) -> None:
    services = create_degraded_services(tmp_path / "degraded.db")
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))

    health = client.get("/api/health")
    sessions = client.get("/api/sessions", params={"user_id": "user"})
    chat = post_chat(client, "user", "window", "hello")

    assert health.status_code == 200
    assert health.json()["llm_configured"] is False
    assert health.json()["database"] == "available"
    assert sessions.status_code == 200
    assert chat.status_code == 503
    assert chat.json()["error"]["code"] == "llm_unavailable"

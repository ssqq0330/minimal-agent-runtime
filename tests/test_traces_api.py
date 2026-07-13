"""Offline FastAPI tests for user-scoped Trace routes."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.api_helpers import final_content, make_test_services, tool_content


def post_chat(client: TestClient, user: str, session: str, message: str):
    return client.post(
        "/api/chat",
        json={"user_id": user, "session_id": session, "message": message},
    )


def test_chat_trace_can_be_listed_filtered_and_is_newest_first(tmp_path: Path) -> None:
    services, _ = make_test_services(
        tmp_path,
        [final_content("one"), final_content("two")],
    )
    services.store.create_session("user", "one")
    services.store.create_session("user", "two")
    client = TestClient(create_app(services))
    first = post_chat(client, "user", "one", "first").json()["run_id"]
    second = post_chat(client, "user", "two", "second").json()["run_id"]

    listed = client.get("/api/traces", params={"user_id": "user"})
    filtered = client.get(
        "/api/traces",
        params={
            "user_id": "user",
            "session_id": "one",
            "status": "completed",
        },
    )

    assert [item["run_id"] for item in listed.json()] == [second, first]
    assert [item["run_id"] for item in filtered.json()] == [first]


def test_trace_detail_events_are_ordered_and_contain_real_tool_results(
    tmp_path: Path,
) -> None:
    services, _ = make_test_services(
        tmp_path,
        [
            tool_content(
                [
                    {
                        "id": "calc",
                        "name": "calculator",
                        "arguments": {"expression": "12 * 5"},
                    },
                    {
                        "id": "todo",
                        "name": "todo",
                        "arguments": {"action": "add", "content": "检查"},
                    },
                ]
            ),
            final_content("done"),
        ],
    )
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))
    run_id = post_chat(client, "user", "window", "execute").json()["run_id"]

    response = client.get(
        "/api/traces/{}".format(run_id),
        params={"user_id": "user"},
    )
    value = response.json()
    results = [
        item for item in value["events"] if item["event_type"] == "tool_result"
    ]

    assert response.status_code == 200
    assert value["run"]["run_id"] == run_id
    assert [item["sequence"] for item in value["events"]] == list(
        range(1, len(value["events"]) + 1)
    )
    assert [item["payload"]["tool_name"] for item in results] == [
        "calculator",
        "todo",
    ]
    assert results[0]["payload"]["output"]["result"] == 60
    assert results[1]["payload"]["output"]["todo"]["content"] == "检查"


def test_other_user_cannot_read_or_delete_trace(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [final_content()])
    services.store.create_session("user-a", "window")
    client = TestClient(create_app(services))
    run_id = post_chat(client, "user-a", "window", "hello").json()["run_id"]

    read = client.get(
        "/api/traces/{}".format(run_id),
        params={"user_id": "user-b"},
    )
    delete = client.delete(
        "/api/traces/{}".format(run_id),
        params={"user_id": "user-b"},
    )

    assert read.status_code == 404
    assert delete.status_code == 404
    assert services.trace_recorder.get_trace(run_id).run.user_id == "user-a"


def test_delete_trace_and_missing_id_return_expected_status(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [final_content()])
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))
    run_id = post_chat(client, "user", "window", "hello").json()["run_id"]

    deleted = client.delete(
        "/api/traces/{}".format(run_id),
        params={"user_id": "user"},
    )
    missing = client.get(
        "/api/traces/{}".format(run_id),
        params={"user_id": "user"},
    )

    assert deleted.status_code == 204
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "trace_not_found"


def test_trace_list_limit_and_status_are_validated(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    client = TestClient(create_app(services))
    too_large = client.get(
        "/api/traces",
        params={"user_id": "user", "limit": 201},
    )
    invalid_status = client.get(
        "/api/traces",
        params={"user_id": "user", "status": "unknown"},
    )

    assert too_large.status_code == 422
    assert too_large.json()["error"]["code"] == "validation_error"
    assert invalid_status.status_code == 422
    assert invalid_status.json()["error"]["code"] == "trace_invalid"


def test_trace_response_excludes_secrets_and_runtime_messages(tmp_path: Path) -> None:
    services, _ = make_test_services(
        tmp_path,
        [final_content("answer", "api_key=super-secret")],
    )
    services.store.create_session("user", "window")
    client = TestClient(create_app(services))
    run_id = post_chat(client, "user", "window", "hello").json()["run_id"]

    response = client.get(
        "/api/traces/{}".format(run_id),
        params={"user_id": "user"},
    )
    serialized = json.dumps(response.json(), ensure_ascii=False)

    assert response.status_code == 200
    assert "super-secret" not in serialized
    assert '"messages"' not in serialized
    assert "system_prompt" not in serialized
    assert "raw_response" not in serialized

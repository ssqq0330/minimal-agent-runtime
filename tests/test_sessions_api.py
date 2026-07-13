"""Offline FastAPI tests for Session, history, and Todo routes."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from tests.api_helpers import make_test_services


def test_create_session_with_generated_and_explicit_ids(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    client = TestClient(create_app(services))

    generated = client.post(
        "/api/sessions",
        json={"user_id": "user-a", "title": "自动窗口"},
    )
    explicit = client.post(
        "/api/sessions",
        json={
            "user_id": "user-a",
            "session_id": "window-1",
            "title": "天气窗口",
        },
    )

    assert generated.status_code == 201
    assert generated.json()["session_id"]
    assert explicit.status_code == 201
    assert explicit.json()["session_id"] == "window-1"
    assert explicit.json()["title"] == "天气窗口"


def test_duplicate_session_returns_uniform_conflict(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    client = TestClient(create_app(services))
    body = {"user_id": "user-a", "session_id": "same", "title": "one"}
    assert client.post("/api/sessions", json=body).status_code == 201

    response = client.post("/api/sessions", json=body)

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "session_conflict", "message": "Session 已存在"}
    }


def test_list_detail_and_rename_are_user_scoped(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    for user_id, session_id in (
        ("user-a", "shared"),
        ("user-b", "shared"),
        ("user-a", "other"),
    ):
        services.store.create_session(user_id, session_id, user_id)
    client = TestClient(create_app(services))

    listed = client.get("/api/sessions", params={"user_id": "user-a"})
    detail = client.get(
        "/api/sessions/shared",
        params={"user_id": "user-a"},
    )
    renamed = client.patch(
        "/api/sessions/shared",
        json={"user_id": "user-a", "title": "新标题"},
    )

    assert listed.status_code == 200
    assert {item["session_id"] for item in listed.json()} == {"shared", "other"}
    assert all(item["user_id"] == "user-a" for item in listed.json())
    assert detail.json()["title"] == "user-a"
    assert renamed.json()["title"] == "新标题"
    assert services.store.get_session("user-b", "shared").title == "user-b"


def test_missing_detail_and_delete_other_user_return_not_found(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    services.store.create_session("user-b", "same")
    client = TestClient(create_app(services))

    missing = client.get("/api/sessions/missing", params={"user_id": "user-a"})
    protected = client.delete("/api/sessions/same", params={"user_id": "user-a"})
    assert services.store.get_session("user-b", "same") is not None
    deleted = client.delete("/api/sessions/same", params={"user_id": "user-b"})

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "session_not_found"
    assert protected.status_code == 404
    assert deleted.status_code == 204


def test_messages_are_old_to_new_and_limit_is_validated(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    services.store.create_session("user", "window")
    for index in range(1, 4):
        services.store.add_exchange(
            "user",
            "window",
            "q{}".format(index),
            "a{}".format(index),
        )
    client = TestClient(create_app(services))

    all_messages = client.get(
        "/api/sessions/window/messages",
        params={"user_id": "user", "limit": 50},
    )
    limited = client.get(
        "/api/sessions/window/messages",
        params={"user_id": "user", "limit": 2},
    )
    invalid = client.get(
        "/api/sessions/window/messages",
        params={"user_id": "user", "limit": 501},
    )

    assert [item["content"] for item in all_messages.json()] == [
        "q1",
        "a1",
        "q2",
        "a2",
        "q3",
        "a3",
    ]
    assert [item["content"] for item in limited.json()] == ["q3", "a3"]
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_clear_messages_preserves_session_and_todo(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    services.store.create_session("user", "window")
    services.store.add_exchange("user", "window", "q", "a")
    services.store.add_todo("user", "window", "keep")
    client = TestClient(create_app(services))

    response = client.delete(
        "/api/sessions/window/messages",
        params={"user_id": "user"},
    )

    assert response.status_code == 200
    assert response.json() == {"deleted_count": 2}
    assert services.store.get_session("user", "window") is not None
    assert services.store.count_messages("user", "window") == 0
    assert services.store.list_todos("user", "window")[0].content == "keep"


def test_todo_query_is_session_scoped(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    for session_id, content in (("one", "todo one"), ("two", "todo two")):
        services.store.create_session("user", session_id)
        services.store.add_todo("user", session_id, content)
    client = TestClient(create_app(services))

    first = client.get("/api/sessions/one/todos", params={"user_id": "user"})
    second = client.get("/api/sessions/two/todos", params={"user_id": "user"})

    assert [item["content"] for item in first.json()] == ["todo one"]
    assert [item["content"] for item in second.json()] == ["todo two"]


def test_body_whitespace_validation_uses_uniform_error(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path)
    client = TestClient(create_app(services))
    response = client.post(
        "/api/sessions",
        json={"user_id": "  ", "session_id": "x", "title": "title"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"

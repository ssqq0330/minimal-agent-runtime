"""Tests for SQLite Session, message, and Todo persistence."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest

from app.memory import (
    DuplicateSessionError,
    SessionNotFoundError,
    SQLiteStore,
    TodoNotFoundError,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "database" / "agent.db"


@pytest.fixture
def store(db_path: Path) -> SQLiteStore:
    return SQLiteStore(db_path)


def create_session(
    store: SQLiteStore,
    user_id: str = "user-1",
    session_id: str = "session-1",
) -> None:
    store.create_session(user_id, session_id)


def test_initialization_creates_temporary_database(
    store: SQLiteStore,
    db_path: Path,
) -> None:
    assert db_path.exists()
    assert store.db_path == db_path


def test_initialization_creates_parent_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "directory" / "agent.db"

    SQLiteStore(db_path)

    assert db_path.parent.is_dir()


def test_initialize_is_idempotent(store: SQLiteStore) -> None:
    store.initialize()
    store.initialize()

    assert store.list_sessions("user-1") == []


def test_reopened_store_retains_data(db_path: Path) -> None:
    first_store = SQLiteStore(db_path)
    first_store.create_session("user-1", "session-1", "Persistent")
    first_store.add_message("user-1", "session-1", "user", "Remember me")

    reopened_store = SQLiteStore(db_path)

    assert reopened_store.get_session("user-1", "session-1").title == "Persistent"
    assert reopened_store.list_messages("user-1", "session-1")[0].content == "Remember me"


def test_create_session_with_explicit_id(store: SQLiteStore) -> None:
    session = store.create_session("user-1", "session-1", "Title")

    assert session.user_id == "user-1"
    assert session.session_id == "session-1"
    assert session.title == "Title"
    assert datetime.fromisoformat(session.created_at).tzinfo is not None
    assert session.to_dict()["session_id"] == "session-1"


def test_create_session_generates_id(store: SQLiteStore) -> None:
    session = store.create_session("user-1")

    assert len(session.session_id) == 32
    assert store.get_session("user-1", session.session_id) is not None


def test_create_session_uses_default_title(store: SQLiteStore) -> None:
    assert store.create_session("user-1", "session-1").title == "新会话"


def test_duplicate_session_for_same_user_fails(store: SQLiteStore) -> None:
    create_session(store)

    with pytest.raises(DuplicateSessionError, match="already exists"):
        create_session(store)


def test_different_users_can_share_session_id(store: SQLiteStore) -> None:
    store.create_session("user-a", "same-id", "A")
    store.create_session("user-b", "same-id", "B")

    assert store.get_session("user-a", "same-id").title == "A"
    assert store.get_session("user-b", "same-id").title == "B"


def test_get_session_is_user_scoped(store: SQLiteStore) -> None:
    store.create_session("user-a", "session", "A")

    assert store.get_session("user-a", "session") is not None
    assert store.get_session("user-b", "session") is None


def test_list_sessions_returns_only_user_sessions(store: SQLiteStore) -> None:
    store.create_session("user-a", "a1")
    store.create_session("user-a", "a2")
    store.create_session("user-b", "b1")

    assert {item.session_id for item in store.list_sessions("user-a")} == {"a1", "a2"}


def test_list_sessions_orders_latest_update_first(store: SQLiteStore) -> None:
    store.create_session("user", "first")
    store.create_session("user", "second")
    store.touch_session("user", "first")

    assert [item.session_id for item in store.list_sessions("user")][:2] == [
        "first",
        "second",
    ]


def test_update_session_title(store: SQLiteStore) -> None:
    create_session(store)

    updated = store.update_session_title("user-1", "session-1", "New title")

    assert updated.title == "New title"
    assert store.get_session("user-1", "session-1").title == "New title"


def test_update_missing_session_fails(store: SQLiteStore) -> None:
    with pytest.raises(SessionNotFoundError):
        store.update_session_title("user", "missing", "Title")


def test_touch_session_updates_timestamp(store: SQLiteStore) -> None:
    session = store.create_session("user", "session")

    touched = store.touch_session("user", "session")

    assert touched.updated_at >= session.updated_at


def test_delete_session(store: SQLiteStore) -> None:
    create_session(store)

    assert store.delete_session("user-1", "session-1") is True
    assert store.get_session("user-1", "session-1") is None


def test_delete_missing_session_returns_false(store: SQLiteStore) -> None:
    assert store.delete_session("user", "missing") is False


def test_user_cannot_delete_other_users_same_session(store: SQLiteStore) -> None:
    store.create_session("user-b", "same")

    assert store.delete_session("user-a", "same") is False
    assert store.get_session("user-b", "same") is not None


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_add_message_roles(store: SQLiteStore, role: str) -> None:
    create_session(store)

    message = store.add_message("user-1", "session-1", role, "Content")

    assert message.role == role
    assert message.content == "Content"
    assert message.to_dict()["id"] == message.id
    assert datetime.fromisoformat(message.created_at).tzinfo is not None


def test_add_message_requires_existing_session(store: SQLiteStore) -> None:
    with pytest.raises(SessionNotFoundError):
        store.add_message("user", "missing", "user", "Content")


def test_add_message_rejects_invalid_role(store: SQLiteStore) -> None:
    create_session(store)

    with pytest.raises(ValueError, match="role"):
        store.add_message("user-1", "session-1", "system", "Content")


def test_add_message_rejects_empty_content(store: SQLiteStore) -> None:
    create_session(store)

    with pytest.raises(ValueError, match="content"):
        store.add_message("user-1", "session-1", "user", "  ")


def test_message_metadata_round_trips(store: SQLiteStore) -> None:
    create_session(store)
    metadata = {"source": "测试", "nested": {"count": 2}}

    store.add_message("user-1", "session-1", "user", "Content", metadata)
    restored = store.list_messages("user-1", "session-1")[0]

    assert restored.metadata == metadata
    assert "测试" in restored.metadata["source"]


def test_message_metadata_must_be_serializable(store: SQLiteStore) -> None:
    create_session(store)

    with pytest.raises(ValueError, match="JSON serializable"):
        store.add_message(
            "user-1",
            "session-1",
            "user",
            "Content",
            {"bad": {1, 2}},
        )


def test_list_messages_returns_oldest_to_newest(store: SQLiteStore) -> None:
    create_session(store)
    for content in ["one", "two", "three"]:
        store.add_message("user-1", "session-1", "user", content)

    assert [item.content for item in store.list_messages("user-1", "session-1")] == [
        "one",
        "two",
        "three",
    ]


def test_message_limit_returns_recent_items_in_order(store: SQLiteStore) -> None:
    create_session(store)
    for content in ["one", "two", "three"]:
        store.add_message("user-1", "session-1", "user", content)

    messages = store.list_messages("user-1", "session-1", limit=2)

    assert [item.content for item in messages] == ["two", "three"]


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_message_limit_must_be_positive_integer(store: SQLiteStore, limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        store.list_messages("user", "session", limit=limit)  # type: ignore[arg-type]


def test_count_and_clear_messages(store: SQLiteStore) -> None:
    create_session(store)
    store.add_message("user-1", "session-1", "user", "one")
    store.add_message("user-1", "session-1", "assistant", "two")

    assert store.count_messages("user-1", "session-1") == 2
    assert store.clear_messages("user-1", "session-1") == 2
    assert store.count_messages("user-1", "session-1") == 0
    assert store.get_session("user-1", "session-1") is not None


def test_messages_are_isolated_by_session_and_user(store: SQLiteStore) -> None:
    for user_id, session_id in [("a", "one"), ("a", "two"), ("b", "one")]:
        store.create_session(user_id, session_id)
        store.add_message(user_id, session_id, "user", "{}-{}".format(user_id, session_id))

    assert [item.content for item in store.list_messages("a", "one")] == ["a-one"]
    assert [item.content for item in store.list_messages("a", "two")] == ["a-two"]
    assert [item.content for item in store.list_messages("b", "one")] == ["b-one"]


def test_add_message_updates_session(store: SQLiteStore) -> None:
    session = store.create_session("user", "session")

    store.add_message("user", "session", "user", "message")

    assert store.get_session("user", "session").updated_at >= session.updated_at


def test_todo_ids_increment_per_session(store: SQLiteStore) -> None:
    create_session(store)

    first = store.add_todo("user-1", "session-1", "First")
    second = store.add_todo("user-1", "session-1", "Second")

    assert first.id == 1
    assert second.id == 2
    assert first.to_dict()["completed"] is False


def test_todo_ids_start_at_one_in_each_scope(store: SQLiteStore) -> None:
    for user_id, session_id in [("a", "one"), ("a", "two"), ("b", "one")]:
        store.create_session(user_id, session_id)

    assert store.add_todo("a", "one", "A1").id == 1
    assert store.add_todo("a", "two", "A2").id == 1
    assert store.add_todo("b", "one", "B1").id == 1


def test_todos_are_isolated_and_sorted(store: SQLiteStore) -> None:
    for user_id, session_id in [("a", "one"), ("a", "two"), ("b", "one")]:
        store.create_session(user_id, session_id)
    store.add_todo("a", "one", "one")
    store.add_todo("a", "one", "two")
    store.add_todo("a", "two", "other session")
    store.add_todo("b", "one", "other user")

    todos = store.list_todos("a", "one")

    assert [todo.id for todo in todos] == [1, 2]
    assert [todo.content for todo in todos] == ["one", "two"]


def test_complete_todo_is_idempotent(store: SQLiteStore) -> None:
    create_session(store)
    store.add_todo("user-1", "session-1", "Todo")

    completed = store.complete_todo("user-1", "session-1", 1)
    completed_again = store.complete_todo("user-1", "session-1", 1)

    assert completed.completed is True
    assert completed.completed_at is not None
    assert datetime.fromisoformat(completed.completed_at).tzinfo is not None
    assert completed_again.completed_at == completed.completed_at


def test_complete_missing_todo_fails(store: SQLiteStore) -> None:
    create_session(store)

    with pytest.raises(TodoNotFoundError, match="not found"):
        store.complete_todo("user-1", "session-1", 99)


def test_delete_todo_and_missing_behavior(store: SQLiteStore) -> None:
    create_session(store)
    store.add_todo("user-1", "session-1", "Todo")

    assert store.delete_todo("user-1", "session-1", 1) is True
    assert store.delete_todo("user-1", "session-1", 1) is False


def test_deleted_todo_id_is_not_reused(store: SQLiteStore) -> None:
    create_session(store)
    store.add_todo("user-1", "session-1", "One")
    store.add_todo("user-1", "session-1", "Two")
    store.delete_todo("user-1", "session-1", 2)

    assert store.add_todo("user-1", "session-1", "Three").id == 3


def test_concurrent_todo_ids_are_unique_and_sequential(store: SQLiteStore) -> None:
    create_session(store)

    with ThreadPoolExecutor(max_workers=8) as executor:
        records = list(
            executor.map(
                lambda index: store.add_todo(
                    "user-1",
                    "session-1",
                    "Todo {}".format(index),
                ),
                range(20),
            )
        )

    assert sorted(record.id for record in records) == list(range(1, 21))
    assert [record.id for record in store.list_todos("user-1", "session-1")] == list(
        range(1, 21)
    )


def test_clear_todos_returns_count(store: SQLiteStore) -> None:
    create_session(store)
    store.add_todo("user-1", "session-1", "One")
    store.add_todo("user-1", "session-1", "Two")

    assert store.clear_todos("user-1", "session-1") == 2
    assert store.list_todos("user-1", "session-1") == []


def test_add_todo_updates_session(store: SQLiteStore) -> None:
    session = store.create_session("user", "session")

    store.add_todo("user", "session", "Todo")

    assert store.get_session("user", "session").updated_at >= session.updated_at


def test_add_todo_requires_session(store: SQLiteStore) -> None:
    with pytest.raises(SessionNotFoundError):
        store.add_todo("user", "missing", "Todo")


def test_delete_session_cascades_messages_and_todos(store: SQLiteStore) -> None:
    create_session(store)
    store.add_message("user-1", "session-1", "user", "Message")
    store.add_todo("user-1", "session-1", "Todo")

    store.delete_session("user-1", "session-1")

    assert store.list_messages("user-1", "session-1") == []
    assert store.list_todos("user-1", "session-1") == []


def test_cascade_delete_is_user_scoped(store: SQLiteStore) -> None:
    for user_id in ["a", "b"]:
        store.create_session(user_id, "same")
        store.add_message(user_id, "same", "user", user_id)
        store.add_todo(user_id, "same", user_id)

    store.delete_session("a", "same")

    assert store.list_messages("b", "same")[0].content == "b"
    assert store.list_todos("b", "same")[0].content == "b"


@pytest.mark.parametrize(
    ("method_name", "arguments"),
    [
        ("create_session", ("  ", "session")),
        ("get_session", ("user", "  ")),
        ("create_session", ("user", "session", "  ")),
    ],
)
def test_empty_identity_and_title_validation(
    store: SQLiteStore,
    method_name: str,
    arguments: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError):
        getattr(store, method_name)(*arguments)


def test_empty_todo_content_fails(store: SQLiteStore) -> None:
    create_session(store)

    with pytest.raises(ValueError, match="content"):
        store.add_todo("user-1", "session-1", "  ")


@pytest.mark.parametrize("todo_id", [True, 0, -1])
def test_invalid_todo_id_fails(store: SQLiteStore, todo_id: object) -> None:
    create_session(store)

    with pytest.raises(ValueError, match="todo_id"):
        store.complete_todo("user-1", "session-1", todo_id)  # type: ignore[arg-type]

"""Tests for the optional SQLite-backed TodoTool mode."""

from pathlib import Path

import pytest

from app.memory import SQLiteStore
from app.tools import TodoTool, ToolContext, create_default_registry


@pytest.fixture
def store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "persistent" / "agent.db")


@pytest.fixture
def context() -> ToolContext:
    return ToolContext("user-1", "session-1")


@pytest.fixture
def persistent_tool(store: SQLiteStore, context: ToolContext) -> TodoTool:
    store.create_session(context.user_id, context.session_id)
    return TodoTool(store=store)


def test_persistent_todo_add_and_list(
    persistent_tool: TodoTool,
    context: ToolContext,
) -> None:
    added = persistent_tool.execute(
        {"action": "add", "content": "Persistent item"},
        context,
    )
    listed = persistent_tool.execute({"action": "list"}, context)

    assert added.success is True
    assert added.output["todo"]["id"] == 1
    assert listed.output["todos"][0]["content"] == "Persistent item"


def test_persistent_todo_complete(
    persistent_tool: TodoTool,
    context: ToolContext,
) -> None:
    persistent_tool.execute({"action": "add", "content": "Item"}, context)

    result = persistent_tool.execute({"action": "complete", "todo_id": 1}, context)

    assert result.success is True
    assert result.output["todo"]["completed"] is True
    assert result.output["todo"]["completed_at"] is not None


def test_persistent_todo_delete(
    persistent_tool: TodoTool,
    context: ToolContext,
) -> None:
    persistent_tool.execute({"action": "add", "content": "Item"}, context)

    result = persistent_tool.execute({"action": "delete", "todo_id": 1}, context)

    assert result.success is True
    assert result.output["deleted"]["id"] == 1
    assert persistent_tool.execute({"action": "list"}, context).output["todos"] == []


def test_data_survives_new_tool_instance(
    persistent_tool: TodoTool,
    store: SQLiteStore,
    context: ToolContext,
) -> None:
    persistent_tool.execute({"action": "add", "content": "Item"}, context)

    recreated_tool = TodoTool(store=store)

    assert recreated_tool.execute({"action": "list"}, context).output["todos"][0][
        "content"
    ] == "Item"


def test_data_survives_new_store_instance(
    persistent_tool: TodoTool,
    store: SQLiteStore,
    context: ToolContext,
) -> None:
    persistent_tool.execute({"action": "add", "content": "Item"}, context)

    recreated_store = SQLiteStore(store.db_path)
    recreated_tool = TodoTool(store=recreated_store)

    assert len(recreated_tool.execute({"action": "list"}, context).output["todos"]) == 1


def test_persistent_todo_isolates_sessions_and_users(store: SQLiteStore) -> None:
    contexts = [
        ToolContext("user-a", "session-1"),
        ToolContext("user-a", "session-2"),
        ToolContext("user-b", "session-1"),
    ]
    for item_context in contexts:
        store.create_session(item_context.user_id, item_context.session_id)
    tool = TodoTool(store=store)

    tool.execute({"action": "add", "content": "Only A1"}, contexts[0])

    assert len(tool.execute({"action": "list"}, contexts[0]).output["todos"]) == 1
    assert tool.execute({"action": "list"}, contexts[1]).output["todos"] == []
    assert tool.execute({"action": "list"}, contexts[2]).output["todos"] == []


def test_add_without_session_returns_failure(store: SQLiteStore, context: ToolContext) -> None:
    result = TodoTool(store=store).execute(
        {"action": "add", "content": "Item"},
        context,
    )

    assert result.success is False
    assert "Session" in result.error


def test_missing_persistent_todo_returns_failure(
    persistent_tool: TodoTool,
    context: ToolContext,
) -> None:
    result = persistent_tool.execute({"action": "complete", "todo_id": 99}, context)

    assert result.success is False
    assert "not found" in result.error


def test_default_registry_can_use_persistent_todo(
    store: SQLiteStore,
    context: ToolContext,
) -> None:
    store.create_session(context.user_id, context.session_id)
    registry = create_default_registry(todo_store=store)

    result = registry.execute(
        "todo",
        {"action": "add", "content": "Registry item"},
        context,
    )

    assert result.success is True
    assert store.list_todos(context.user_id, context.session_id)[0].content == "Registry item"


def test_default_registry_without_store_keeps_memory_mode(context: ToolContext) -> None:
    registry = create_default_registry()

    result = registry.execute(
        "todo",
        {"action": "add", "content": "Memory item"},
        context,
    )

    assert result.success is True
    assert registry.execute("todo", {"action": "list"}, context).output["todos"][0][
        "content"
    ] == "Memory item"


def test_other_default_tools_ignore_todo_store(
    store: SQLiteStore,
    context: ToolContext,
) -> None:
    registry = create_default_registry(todo_store=store)

    calculator = registry.execute("calculator", {"expression": "2 + 3"}, context)
    search = registry.execute("search", {"query": "FastAPI"}, context)

    assert calculator.success is True
    assert calculator.output["result"] == 5
    assert search.success is True
    assert search.output["source"] == "mock"


def test_persistent_clear_requires_context(
    persistent_tool: TodoTool,
) -> None:
    with pytest.raises(ValueError, match="context"):
        persistent_tool.clear()


def test_persistent_clear_only_clears_requested_scope(
    store: SQLiteStore,
) -> None:
    first = ToolContext("user", "one")
    second = ToolContext("user", "two")
    store.create_session(first.user_id, first.session_id)
    store.create_session(second.user_id, second.session_id)
    tool = TodoTool(store=store)
    tool.execute({"action": "add", "content": "First"}, first)
    tool.execute({"action": "add", "content": "Second"}, second)

    tool.clear(first)

    assert tool.execute({"action": "list"}, first).output["todos"] == []
    assert len(tool.execute({"action": "list"}, second).output["todos"]) == 1

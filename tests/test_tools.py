"""Tests for the standalone tool system."""

from typing import Any, Dict

import pytest

from app.tools import (
    BaseTool,
    CalculatorTool,
    MockSearchTool,
    TodoTool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    create_default_registry,
)


CONTEXT = ToolContext(user_id="user-a", session_id="session-a")


class ExplodingTool(BaseTool):
    """Test double used to verify Registry exception handling."""

    name = "exploding"
    description = "Raises an unexpected error."
    parameters_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }

    def execute(
        self,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        raise RuntimeError("expected test failure")


@pytest.fixture
def calculator() -> CalculatorTool:
    """Provide an isolated calculator instance."""
    return CalculatorTool()


@pytest.fixture
def search() -> MockSearchTool:
    """Provide an isolated mock-search instance."""
    return MockSearchTool()


@pytest.fixture
def todo() -> TodoTool:
    """Provide an isolated todo store for every test."""
    return TodoTool()


def test_calculator_addition(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "2 + 3"}, CONTEXT)

    assert result.success is True
    assert result.output["result"] == 5


def test_calculator_parenthesized_multiplication(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "12 * (3 + 2)"}, CONTEXT)

    assert result.success is True
    assert result.output == {"expression": "12 * (3 + 2)", "result": 60}


def test_calculator_rejects_division_by_zero(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "1 / 0"}, CONTEXT)

    assert result.success is False
    assert "zero" in result.error.lower()


def test_calculator_rejects_import(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "__import__('os')"}, CONTEXT)

    assert result.success is False


def test_calculator_rejects_function_call(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "abs(1)"}, CONTEXT)

    assert result.success is False


def test_calculator_rejects_variable(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "total + 1"}, CONTEXT)

    assert result.success is False


def test_calculator_rejects_missing_expression(calculator: CalculatorTool) -> None:
    result = calculator.execute({}, CONTEXT)

    assert result.success is False
    assert "expression" in result.error


def test_calculator_rejects_extra_arguments(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "1", "extra": True}, CONTEXT)

    assert result.success is False
    assert "Unexpected" in result.error


def test_calculator_rejects_overlong_expression(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "1" * 201}, CONTEXT)

    assert result.success is False
    assert "200" in result.error


def test_calculator_rejects_large_exponent(calculator: CalculatorTool) -> None:
    result = calculator.execute({"expression": "2 ** 101"}, CONTEXT)

    assert result.success is False
    assert "Exponent" in result.error


def test_search_finds_fastapi(search: MockSearchTool) -> None:
    result = search.execute({"query": "fastapi"}, CONTEXT)

    assert result.success is True
    assert result.output["results"][0]["title"] == "FastAPI"
    assert result.output["source"] == "mock"


def test_search_finds_agent(search: MockSearchTool) -> None:
    result = search.execute({"query": "Agent"}, CONTEXT)

    assert result.success is True
    assert any(item["title"] == "Agent Runtime" for item in result.output["results"])


def test_search_unknown_query_returns_empty_result(search: MockSearchTool) -> None:
    result = search.execute({"query": "not-in-the-knowledge-base"}, CONTEXT)

    assert result.success is True
    assert result.output["results"] == []
    assert "message" in result.output


def test_search_limit_one(search: MockSearchTool) -> None:
    result = search.execute({"query": "Python", "limit": 1}, CONTEXT)

    assert result.success is True
    assert len(result.output["results"]) <= 1


def test_search_rejects_large_limit(search: MockSearchTool) -> None:
    result = search.execute({"query": "Python", "limit": 6}, CONTEXT)

    assert result.success is False
    assert "at most 5" in result.error


def test_search_rejects_small_limit(search: MockSearchTool) -> None:
    result = search.execute({"query": "Python", "limit": 0}, CONTEXT)

    assert result.success is False
    assert "at least 1" in result.error


def test_search_rejects_missing_query(search: MockSearchTool) -> None:
    result = search.execute({}, CONTEXT)

    assert result.success is False
    assert "query" in result.error


def test_search_rejects_extra_arguments(search: MockSearchTool) -> None:
    result = search.execute({"query": "Python", "unexpected": "value"}, CONTEXT)

    assert result.success is False
    assert "Unexpected" in result.error


def test_todo_add(todo: TodoTool) -> None:
    result = todo.execute({"action": "add", "content": "Write tests"}, CONTEXT)

    assert result.success is True
    assert result.output["todo"]["id"] == 1
    assert result.output["todo"]["completed"] is False
    assert "+00:00" in result.output["todo"]["created_at"]


def test_todo_list(todo: TodoTool) -> None:
    todo.execute({"action": "add", "content": "One"}, CONTEXT)

    result = todo.execute({"action": "list"}, CONTEXT)

    assert result.success is True
    assert [item["content"] for item in result.output["todos"]] == ["One"]


def test_todo_complete(todo: TodoTool) -> None:
    todo.execute({"action": "add", "content": "One"}, CONTEXT)

    result = todo.execute({"action": "complete", "todo_id": 1}, CONTEXT)

    assert result.success is True
    assert result.output["todo"]["completed"] is True


def test_todo_delete(todo: TodoTool) -> None:
    todo.execute({"action": "add", "content": "One"}, CONTEXT)

    result = todo.execute({"action": "delete", "todo_id": 1}, CONTEXT)

    assert result.success is True
    assert result.output["deleted"]["id"] == 1
    assert todo.execute({"action": "list"}, CONTEXT).output["todos"] == []


def test_todo_rejects_empty_content(todo: TodoTool) -> None:
    result = todo.execute({"action": "add", "content": "   "}, CONTEXT)

    assert result.success is False
    assert "empty" in result.error


def test_todo_complete_requires_todo_id(todo: TodoTool) -> None:
    result = todo.execute({"action": "complete"}, CONTEXT)

    assert result.success is False
    assert "todo_id" in result.error


def test_todo_isolates_sessions(todo: TodoTool) -> None:
    todo.execute({"action": "add", "content": "Session A"}, CONTEXT)
    other_session = ToolContext(user_id="user-a", session_id="session-b")

    result = todo.execute({"action": "list"}, other_session)

    assert result.success is True
    assert result.output["todos"] == []


def test_todo_isolates_users(todo: TodoTool) -> None:
    todo.execute({"action": "add", "content": "User A"}, CONTEXT)
    other_user = ToolContext(user_id="user-b", session_id="session-a")

    result = todo.execute({"action": "list"}, other_user)

    assert result.success is True
    assert result.output["todos"] == []


def test_todo_reports_unknown_id(todo: TodoTool) -> None:
    result = todo.execute({"action": "delete", "todo_id": 99}, CONTEXT)

    assert result.success is False
    assert "not found" in result.error


def test_todo_clear_resets_data(todo: TodoTool) -> None:
    todo.execute({"action": "add", "content": "One"}, CONTEXT)

    todo.clear()

    result = todo.execute({"action": "list"}, CONTEXT)
    add_result = todo.execute({"action": "add", "content": "New"}, CONTEXT)
    assert result.output["todos"] == []
    assert add_result.output["todo"]["id"] == 1


def test_default_registry_contains_all_tools() -> None:
    registry = create_default_registry()

    assert {tool.name for tool in registry.list_tools()} == {"calculator", "search", "todo"}


def test_registry_returns_tool_schemas() -> None:
    registry = create_default_registry()

    schemas = registry.get_tool_schemas()

    assert {schema["name"] for schema in schemas} == {"calculator", "search", "todo"}
    assert all(schema["parameters"]["type"] == "object" for schema in schemas)


def test_registry_rejects_duplicate_registration() -> None:
    registry = ToolRegistry()
    registry.register(CalculatorTool())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(CalculatorTool())


def test_registry_reports_unknown_tool() -> None:
    result = ToolRegistry().execute("missing", {}, CONTEXT)

    assert result.success is False
    assert "Unknown tool" in result.error


def test_registry_executes_calculator() -> None:
    result = create_default_registry().execute(
        "calculator",
        {"expression": "4 * 5"},
        CONTEXT,
    )

    assert result.success is True
    assert result.output["result"] == 20


def test_registry_converts_unexpected_tool_exception() -> None:
    registry = ToolRegistry()
    registry.register(ExplodingTool())

    result = registry.execute("exploding", {}, CONTEXT)

    assert result.success is False
    assert "expected test failure" in result.error

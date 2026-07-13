"""Thread-safe Todo tool with memory and optional SQLite storage modes."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple

from app.memory.store import SQLiteStore, TodoRecord
from app.tools.base import BaseTool, ToolContext, ToolResult


class TodoTool(BaseTool):
    """Manage todos using memory by default or an injected SQLite store."""

    name = "todo"
    description = "管理当前用户当前会话中的待办事项，支持添加、查看、完成和删除。"
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "list", "complete", "delete"],
            },
            "content": {"type": "string", "description": "待办内容"},
            "todo_id": {"type": "integer", "description": "待办编号"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def __init__(self, store: Optional[SQLiteStore] = None) -> None:
        self._store = store
        self._lock = RLock()
        self._todos: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._next_ids: Dict[Tuple[str, str], int] = {}

    def execute(
        self,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Perform the requested todo operation without leaking other scopes."""
        try:
            validation_error = self.validate_arguments(arguments)
            if validation_error is not None:
                return validation_error

            action = arguments["action"]
            with self._lock:
                if action == "add":
                    return self._add(arguments, context)
                if action == "list":
                    return self._list(context)
                if action == "complete":
                    return self._complete(arguments, context)
                if action == "delete":
                    return self._delete(arguments, context)
            return ToolResult(False, None, "Unsupported todo action.")
        except Exception as error:
            return ToolResult(False, None, "Todo tool failed: {}".format(error))

    def clear(self, context: Optional[ToolContext] = None) -> None:
        """Clear memory data, or one explicit SQLite user/session scope."""
        with self._lock:
            if self._store is not None:
                if context is None:
                    raise ValueError(
                        "context is required when clearing persistent Todo data."
                    )
                self._store.clear_todos(context.user_id, context.session_id)
                return
            self._todos.clear()
            self._next_ids.clear()

    def _add(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        content = arguments.get("content")
        if content is None:
            return ToolResult(False, None, "Missing required argument for add: 'content'.")
        content = content.strip()
        if not content:
            return ToolResult(False, None, "Argument 'content' must not be empty.")

        if self._store is not None:
            todo = self._store.add_todo(
                context.user_id,
                context.session_id,
                content,
            )
            return ToolResult(True, {"todo": self._record_to_tool_dict(todo)})

        key = self._scope_key(context)
        todo_id = self._next_ids.get(key, 1)
        todo = {
            "id": todo_id,
            "content": content,
            "completed": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._todos.setdefault(key, []).append(todo)
        self._next_ids[key] = todo_id + 1
        return ToolResult(True, {"todo": dict(todo)})

    def _list(self, context: ToolContext) -> ToolResult:
        if self._store is not None:
            todos = self._store.list_todos(context.user_id, context.session_id)
            return ToolResult(
                True,
                {"todos": [self._record_to_tool_dict(todo) for todo in todos]},
            )
        todos = self._todos.get(self._scope_key(context), [])
        return ToolResult(True, {"todos": [dict(todo) for todo in todos]})

    def _complete(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        if self._store is not None:
            todo_id = arguments.get("todo_id")
            if todo_id is None:
                return ToolResult(False, None, "Missing required argument: 'todo_id'.")
            todo = self._store.complete_todo(
                context.user_id,
                context.session_id,
                todo_id,
            )
            return ToolResult(True, {"todo": self._record_to_tool_dict(todo)})

        todo_result = self._find_todo(arguments, context)
        if isinstance(todo_result, ToolResult):
            return todo_result
        todo_result["completed"] = True
        return ToolResult(True, {"todo": dict(todo_result)})

    def _delete(self, arguments: Dict[str, Any], context: ToolContext) -> ToolResult:
        if self._store is not None:
            todo_id = arguments.get("todo_id")
            if todo_id is None:
                return ToolResult(False, None, "Missing required argument: 'todo_id'.")
            existing_todo = next(
                (
                    todo
                    for todo in self._store.list_todos(
                        context.user_id,
                        context.session_id,
                    )
                    if todo.id == todo_id
                ),
                None,
            )
            if existing_todo is None:
                return ToolResult(
                    False,
                    None,
                    "Todo with id {} was not found.".format(todo_id),
                )
            deleted = self._store.delete_todo(
                context.user_id,
                context.session_id,
                todo_id,
            )
            if not deleted:
                return ToolResult(
                    False,
                    None,
                    "Todo with id {} was not found.".format(todo_id),
                )
            return ToolResult(
                True,
                {"deleted": self._record_to_tool_dict(existing_todo)},
            )

        todo_result = self._find_todo(arguments, context)
        if isinstance(todo_result, ToolResult):
            return todo_result
        todos = self._todos[self._scope_key(context)]
        todos.remove(todo_result)
        return ToolResult(True, {"deleted": dict(todo_result)})

    def _find_todo(
        self,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> Any:
        todo_id = arguments.get("todo_id")
        if todo_id is None:
            return ToolResult(False, None, "Missing required argument: 'todo_id'.")
        if todo_id < 1:
            return ToolResult(False, None, "Argument 'todo_id' must be a positive integer.")

        for todo in self._todos.get(self._scope_key(context), []):
            if todo["id"] == todo_id:
                return todo
        return ToolResult(False, None, "Todo with id {} was not found.".format(todo_id))

    @staticmethod
    def _scope_key(context: ToolContext) -> Tuple[str, str]:
        return (context.user_id, context.session_id)

    @staticmethod
    def _record_to_tool_dict(todo: TodoRecord) -> Dict[str, Any]:
        return {
            "id": todo.id,
            "content": todo.content,
            "completed": todo.completed,
            "created_at": todo.created_at,
            "completed_at": todo.completed_at,
        }

"""Registry for the application's custom tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.tools.base import BaseTool, ToolContext, ToolResult
from app.security import sanitized_exception_message

if TYPE_CHECKING:
    from app.memory.store import SQLiteStore


class ToolRegistry:
    """Store and invoke named tools without depending on an Agent framework."""

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool, rejecting duplicate names."""
        if self.has(tool.name):
            raise ValueError("A tool named '{}' is already registered.".format(tool.name))
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Remove a tool by name."""
        if not self.has(name):
            raise ValueError("Tool '{}' is not registered.".format(name))
        del self._tools[name]

    def get(self, name: str) -> BaseTool:
        """Return a registered tool or raise a clear lookup error."""
        if not self.has(name):
            raise ValueError("Tool '{}' is not registered.".format(name))
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Return whether a tool name is registered."""
        return name in self._tools

    def list_tools(self) -> List[BaseTool]:
        """Return all registered tools in registration order."""
        return list(self._tools.values())

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return schemas for all currently registered tools."""
        return [tool.get_schema() for tool in self.list_tools()]

    def execute(
        self,
        name: str,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Execute a named tool and convert unexpected failures to ToolResult."""
        if not self.has(name):
            return ToolResult(False, None, "Unknown tool: '{}'".format(name))

        try:
            return self.get(name).execute(arguments, context)
        except Exception as error:
            return ToolResult(
                False,
                None,
                "Tool '{}' failed: {}".format(
                    name,
                    sanitized_exception_message(error, max_chars=500),
                ),
            )


def create_default_registry(
    todo_store: Optional["SQLiteStore"] = None,
) -> ToolRegistry:
    """Build a registry containing the tools available in this milestone."""
    from app.tools.calculator import CalculatorTool
    from app.tools.mock_search import MockSearchTool
    from app.tools.todo import TodoTool

    registry = ToolRegistry()
    registry.register(CalculatorTool())
    registry.register(MockSearchTool())
    registry.register(TodoTool(store=todo_store))
    return registry

"""Local, deliberately non-live search tool for demonstrations."""

from __future__ import annotations

from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolContext, ToolResult


class MockSearchTool(BaseTool):
    """Search a small local knowledge base using case-insensitive matching."""

    name = "search"
    description = (
        "从本地模拟知识库搜索相关信息，用于演示 Agent 的搜索工具调用。"
        "返回结果不是实时互联网信息。"
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要搜索的关键词",
                "maxLength": 1000,
            },
            "limit": {
                "type": "integer",
                "description": "返回结果数量，默认 3",
                "minimum": 1,
                "maximum": 5,
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    _KNOWLEDGE_BASE: List[Dict[str, str]] = [
        {
            "title": "FastAPI",
            "content": "FastAPI is a modern Python web framework for building APIs.",
        },
        {
            "title": "Python",
            "content": "Python is a general-purpose programming language with clear syntax.",
        },
        {
            "title": "Agent Runtime",
            "content": "An Agent Runtime coordinates model responses, tools, and application state.",
        },
        {
            "title": "SQLite",
            "content": "SQLite is an embedded relational database stored in a local file.",
        },
        {
            "title": "东京天气",
            "content": "东京天气示例：晴朗，适合在本地模拟知识库中演示搜索。",
        },
        {
            "title": "北京天气",
            "content": "北京天气示例：多云，示例内容并非实时天气数据。",
        },
    ]

    def execute(
        self,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Return matching entries from the local mock knowledge base."""
        validation_error = self.validate_arguments(arguments)
        if validation_error is not None:
            return validation_error

        query = arguments["query"].strip()
        if not query:
            return ToolResult(False, None, "Argument 'query' must not be empty.")
        if len(query) > 1000:
            return ToolResult(False, None, "Query must not exceed 1000 characters.")

        limit = arguments.get("limit", 3)
        normalized_query = query.casefold()
        results = [
            {"title": entry["title"], "snippet": entry["content"]}
            for entry in self._KNOWLEDGE_BASE
            if normalized_query in entry["title"].casefold()
            or normalized_query in entry["content"].casefold()
        ][:limit]

        output: Dict[str, Any] = {
            "query": arguments["query"],
            "results": results,
            "source": "mock",
        }
        if not results:
            output["message"] = "No matching information was found in the mock knowledge base."
        return ToolResult(True, output)

"""Shared protocol and validation helpers for self-managed tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar, Dict, Optional


@dataclass(frozen=True)
class ToolContext:
    """Identity data that scopes a tool invocation."""

    user_id: str
    session_id: str


@dataclass
class ToolResult:
    """The serializable outcome of a tool invocation."""

    success: bool
    output: Any
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert this result to the response shape used by callers."""
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }


class BaseTool(ABC):
    """Base class for tools implemented by this application."""

    name: ClassVar[str]
    description: ClassVar[str]
    parameters_schema: ClassVar[Dict[str, Any]]

    @abstractmethod
    def execute(
        self,
        arguments: Dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Run the tool with validated arguments and invocation context."""

    def get_schema(self) -> Dict[str, Any]:
        """Return the function-style schema that can later be sent to an LLM."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }

    def validate_arguments(self, arguments: Dict[str, Any]) -> Optional[ToolResult]:
        """Return a failure result when arguments do not match the JSON schema."""
        if not isinstance(arguments, dict):
            return ToolResult(False, None, "Tool arguments must be an object.")

        properties = self.parameters_schema.get("properties", {})
        required = self.parameters_schema.get("required", [])

        for field_name in required:
            if field_name not in arguments:
                return ToolResult(
                    False,
                    None,
                    "Missing required argument: '{}'".format(field_name),
                )

        if self.parameters_schema.get("additionalProperties") is False:
            unexpected = set(arguments) - set(properties)
            if unexpected:
                field_name = sorted(unexpected)[0]
                return ToolResult(
                    False,
                    None,
                    "Unexpected argument: '{}'".format(field_name),
                )

        for field_name, value in arguments.items():
            field_schema = properties.get(field_name)
            if field_schema is None:
                continue

            error = self._validate_value(field_name, value, field_schema)
            if error is not None:
                return ToolResult(False, None, error)

        return None

    @staticmethod
    def _validate_value(
        field_name: str,
        value: Any,
        field_schema: Dict[str, Any],
    ) -> Optional[str]:
        expected_type = field_schema.get("type")
        type_validators = {
            "string": lambda item: isinstance(item, str),
            "number": lambda item: isinstance(item, (int, float))
            and not isinstance(item, bool),
            "integer": lambda item: isinstance(item, int)
            and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "array": lambda item: isinstance(item, list),
            "object": lambda item: isinstance(item, dict),
        }

        if expected_type in type_validators and not type_validators[expected_type](value):
            return "Argument '{}' must be of type {}.".format(
                field_name,
                expected_type,
            )

        allowed_values = field_schema.get("enum")
        if allowed_values is not None and value not in allowed_values:
            return "Argument '{}' must be one of: {}.".format(
                field_name,
                ", ".join(str(item) for item in allowed_values),
            )

        if "minimum" in field_schema and value < field_schema["minimum"]:
            return "Argument '{}' must be at least {}.".format(
                field_name,
                field_schema["minimum"],
            )

        if "maximum" in field_schema and value > field_schema["maximum"]:
            return "Argument '{}' must be at most {}.".format(
                field_name,
                field_schema["maximum"],
            )

        return None

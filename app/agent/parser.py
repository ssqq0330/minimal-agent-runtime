"""Parse structured JSON decisions returned by an LLM."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class AgentOutputParseError(ValueError):
    """Raised when model output does not follow the Agent decision protocol."""


@dataclass
class ParsedToolCall:
    """A validated request to invoke one registered tool."""

    id: str
    name: str
    arguments: Dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Tool call id must be a non-empty string.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool call name must be a non-empty string.")
        if not isinstance(self.arguments, dict):
            raise ValueError("Tool call arguments must be an object.")
        self.id = self.id.strip()
        self.name = self.name.strip()

    def to_dict(self) -> Dict[str, Any]:
        """Return the tool call as a serializable dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "arguments": self.arguments,
        }


@dataclass
class AgentDecision:
    """A final response or a request for one or more tool calls."""

    type: str
    reasoning_summary: str
    answer: Optional[str] = None
    tool_calls: List[ParsedToolCall] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.type, str) or self.type not in {"final", "tool_call"}:
            raise ValueError("Decision type must be 'final' or 'tool_call'.")
        if not isinstance(self.reasoning_summary, str) or not self.reasoning_summary.strip():
            raise ValueError("reasoning_summary must be a non-empty string.")
        if not isinstance(self.tool_calls, list):
            raise ValueError("tool_calls must be a list.")
        if not all(isinstance(tool_call, ParsedToolCall) for tool_call in self.tool_calls):
            raise ValueError("tool_calls must contain ParsedToolCall values.")

        self.reasoning_summary = self.reasoning_summary.strip()
        if self.type == "final":
            if not isinstance(self.answer, str) or not self.answer.strip():
                raise ValueError("A final decision requires a non-empty answer.")
            if self.tool_calls:
                raise ValueError("A final decision cannot contain tool calls.")
            self.answer = self.answer.strip()
        else:
            if self.answer is not None:
                raise ValueError("A tool_call decision cannot contain an answer.")
            if not self.tool_calls:
                raise ValueError("A tool_call decision requires at least one tool call.")

    @property
    def is_final(self) -> bool:
        """Return whether this decision contains the final user-facing answer."""
        return self.type == "final"

    @property
    def requires_tools(self) -> bool:
        """Return whether this decision requests tool execution."""
        return self.type == "tool_call"

    def to_dict(self) -> Dict[str, Any]:
        """Return the complete decision as a serializable dictionary."""
        return {
            "type": self.type,
            "reasoning_summary": self.reasoning_summary,
            "answer": self.answer,
            "tool_calls": [tool_call.to_dict() for tool_call in self.tool_calls],
        }


def parse_llm_output(content: str) -> AgentDecision:
    """Extract and validate the first decodable JSON object in model output."""
    if not isinstance(content, str):
        raise AgentOutputParseError("LLM output must be a string.")
    if not content.strip():
        raise AgentOutputParseError("LLM output must not be empty.")

    response_data = _extract_first_json_object(content)
    return _parse_decision(response_data)


def _extract_first_json_object(content: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    stripped_content = content.strip()

    try:
        top_level_value, end_position = decoder.raw_decode(stripped_content)
    except json.JSONDecodeError:
        top_level_value = None
        end_position = 0
    else:
        if not stripped_content[end_position:].strip():
            if not isinstance(top_level_value, dict):
                raise AgentOutputParseError("LLM output JSON must be an object.")
            return top_level_value

    for position, character in enumerate(content):
        if character != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(content, position)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate

    raise AgentOutputParseError("No valid JSON object was found in LLM output.")


def _parse_decision(data: Dict[str, Any]) -> AgentDecision:
    decision_type = _required_value(data, "type")
    if not isinstance(decision_type, str):
        raise AgentOutputParseError("Field 'type' must be a string.")
    if decision_type not in {"final", "tool_call"}:
        raise AgentOutputParseError("Field 'type' must be 'final' or 'tool_call'.")

    reasoning_summary = _required_value(data, "reasoning_summary")
    if not isinstance(reasoning_summary, str):
        raise AgentOutputParseError("Field 'reasoning_summary' must be a string.")
    if not reasoning_summary.strip():
        raise AgentOutputParseError("Field 'reasoning_summary' must not be empty.")

    if decision_type == "final":
        return _parse_final_decision(data, reasoning_summary)
    return _parse_tool_call_decision(data, reasoning_summary)


def _parse_final_decision(
    data: Dict[str, Any],
    reasoning_summary: str,
) -> AgentDecision:
    answer = _required_value(data, "answer")
    if not isinstance(answer, str):
        raise AgentOutputParseError("Field 'answer' must be a string for final output.")
    if not answer.strip():
        raise AgentOutputParseError("Field 'answer' must not be empty for final output.")

    if "tool_calls" in data:
        tool_calls = data["tool_calls"]
        if not isinstance(tool_calls, list) or tool_calls:
            raise AgentOutputParseError(
                "Field 'tool_calls' must be an empty list for final output."
            )

    return AgentDecision(
        type="final",
        reasoning_summary=reasoning_summary,
        answer=answer,
        tool_calls=[],
    )


def _parse_tool_call_decision(
    data: Dict[str, Any],
    reasoning_summary: str,
) -> AgentDecision:
    if "answer" in data and data["answer"] is not None:
        raise AgentOutputParseError(
            "Field 'answer' must be null or omitted for tool_call output."
        )

    raw_tool_calls = _required_value(data, "tool_calls")
    if not isinstance(raw_tool_calls, list):
        raise AgentOutputParseError("Field 'tool_calls' must be a list.")
    if not raw_tool_calls:
        raise AgentOutputParseError("Field 'tool_calls' must not be empty.")

    parsed_tool_calls: List[ParsedToolCall] = []
    seen_ids = set()
    for index, raw_tool_call in enumerate(raw_tool_calls):
        if not isinstance(raw_tool_call, dict):
            raise AgentOutputParseError(
                "tool_calls[{}] must be an object.".format(index)
            )

        tool_call_id = _required_tool_call_value(raw_tool_call, "id", index)
        if not isinstance(tool_call_id, str):
            raise AgentOutputParseError(
                "tool_calls[{}].id must be a string.".format(index)
            )
        tool_call_id = tool_call_id.strip()
        if not tool_call_id:
            raise AgentOutputParseError(
                "tool_calls[{}].id must not be empty.".format(index)
            )
        if tool_call_id in seen_ids:
            raise AgentOutputParseError(
                "Duplicate tool call id '{}' is not allowed.".format(tool_call_id)
            )
        seen_ids.add(tool_call_id)

        tool_name = _required_tool_call_value(raw_tool_call, "name", index)
        if not isinstance(tool_name, str):
            raise AgentOutputParseError(
                "tool_calls[{}].name must be a string.".format(index)
            )
        tool_name = tool_name.strip()
        if not tool_name:
            raise AgentOutputParseError(
                "tool_calls[{}].name must not be empty.".format(index)
            )

        arguments = _required_tool_call_value(raw_tool_call, "arguments", index)
        if not isinstance(arguments, dict):
            raise AgentOutputParseError(
                "tool_calls[{}].arguments must be an object.".format(index)
            )

        parsed_tool_calls.append(
            ParsedToolCall(
                id=tool_call_id,
                name=tool_name,
                arguments=arguments,
            )
        )

    return AgentDecision(
        type="tool_call",
        reasoning_summary=reasoning_summary,
        answer=None,
        tool_calls=parsed_tool_calls,
    )


def _required_value(data: Dict[str, Any], field_name: str) -> Any:
    if field_name not in data:
        raise AgentOutputParseError("Required field '{}' is missing.".format(field_name))
    return data[field_name]


def _required_tool_call_value(
    tool_call: Dict[str, Any],
    field_name: str,
    index: int,
) -> Any:
    if field_name not in tool_call:
        raise AgentOutputParseError(
            "tool_calls[{}] is missing '{}'.".format(index, field_name)
        )
    return tool_call[field_name]

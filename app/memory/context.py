"""Deterministic character-based management for recalled conversation context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.memory.store import MessageRecord


SUMMARY_TITLE = "【较早会话摘要】"
SUMMARY_INTRO = "以下内容由系统根据较早的对话记录压缩生成，仅用于延续上下文："
MESSAGE_TRUNCATION_MARKER = "……[已截断]"
SUMMARY_TRUNCATION_MARKER = "……[较早历史已进一步压缩]"
CONTEXT_TRUNCATION_MARKER = "……[为控制上下文长度已截断]"
MESSAGE_STRUCTURE_CHARS = 12


class ContextCompressionError(ValueError):
    """Raised when history cannot be normalized or compressed safely."""


@dataclass
class ContextConfig:
    """Limits used by :class:`BasicContextManager`."""

    max_messages: int = 20
    recent_messages: int = 8
    max_chars: int = 12000
    summary_max_chars: int = 4000
    per_message_chars: int = 500

    def __post_init__(self) -> None:
        for field_name in (
            "max_messages",
            "recent_messages",
            "max_chars",
            "summary_max_chars",
            "per_message_chars",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("{} must be an integer.".format(field_name))
            if value <= 0:
                raise ValueError("{} must be greater than 0.".format(field_name))

        if self.recent_messages > self.max_messages:
            raise ValueError(
                "recent_messages must be less than or equal to max_messages."
            )
        if self.summary_max_chars >= self.max_chars:
            raise ValueError("summary_max_chars must be less than max_chars.")
        if self.per_message_chars > self.summary_max_chars:
            raise ValueError(
                "per_message_chars must be less than or equal to "
                "summary_max_chars."
            )


@dataclass
class ContextBuildResult:
    """Normalized context plus statistics describing one build operation."""

    messages: List[Dict[str, str]]
    compressed: bool
    original_message_count: int
    output_message_count: int
    summarized_message_count: int
    retained_recent_count: int
    original_char_count: int
    output_char_count: int
    summary_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable copy without persistence objects."""
        return {
            "messages": [
                {"role": message["role"], "content": message["content"]}
                for message in self.messages
            ],
            "compressed": self.compressed,
            "original_message_count": self.original_message_count,
            "output_message_count": self.output_message_count,
            "summarized_message_count": self.summarized_message_count,
            "retained_recent_count": self.retained_recent_count,
            "original_char_count": self.original_char_count,
            "output_char_count": self.output_char_count,
            "summary_text": self.summary_text,
        }


def estimate_messages_chars(messages: List[Dict[str, str]]) -> int:
    """Estimate context size using role/content length and fixed overhead.

    This is deliberately a character-level approximation, not tokenizer output.
    The input is only read and is never normalized or modified.
    """
    if not isinstance(messages, list):
        raise ContextCompressionError("messages must be a list.")

    total = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ContextCompressionError(
                "messages[{}] must be a dictionary.".format(index)
            )
        role = message.get("role")
        content = message.get("content")
        if not isinstance(role, str) or not isinstance(content, str):
            raise ContextCompressionError(
                "messages[{}] must contain string role and content values.".format(
                    index
                )
            )
        total += len(role) + len(content) + MESSAGE_STRUCTURE_CHARS
    return total


def truncate_text(text: str, max_chars: int, marker: str) -> str:
    """Deterministically truncate text to a positive character limit."""
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars <= 0:
        raise ValueError("max_chars must be a positive integer.")
    if not isinstance(text, str) or not text:
        raise ValueError("text must be a non-empty string.")
    if not isinstance(marker, str) or not marker:
        raise ValueError("marker must be a non-empty string.")
    if len(text) <= max_chars:
        return text
    if max_chars <= len(marker):
        return text[:max_chars]
    prefix = text[: max_chars - len(marker)].rstrip()
    if not prefix:
        return text[:max_chars]
    return prefix + marker


def normalize_history(history: List[Any]) -> List[Dict[str, str]]:
    """Copy supported history records into the Runtime's simple message shape."""
    if not isinstance(history, list):
        raise ContextCompressionError("history must be a list.")

    normalized: List[Dict[str, str]] = []
    for index, item in enumerate(history):
        if isinstance(item, dict):
            role = item.get("role")
            content = item.get("content")
        elif isinstance(item, MessageRecord):
            role = item.role
            content = item.content
        else:
            raise ContextCompressionError(
                "history[{}] must be a MessageRecord or dictionary.".format(index)
            )

        if role is None:
            raise ContextCompressionError(
                "history[{}] is missing role.".format(index)
            )
        if not isinstance(role, str):
            raise ContextCompressionError(
                "history[{}].role must be a string.".format(index)
            )
        if role not in {"user", "assistant"}:
            raise ContextCompressionError(
                "history[{}].role must be 'user' or 'assistant'.".format(index)
            )
        if content is None:
            raise ContextCompressionError(
                "history[{}] is missing content.".format(index)
            )
        if not isinstance(content, str):
            raise ContextCompressionError(
                "history[{}].content must be a string.".format(index)
            )
        content = content.strip()
        if not content:
            raise ContextCompressionError(
                "history[{}].content must not be empty.".format(index)
            )
        normalized.append({"role": role, "content": content})
    return normalized


def _existing_summary_body(content: str) -> str:
    """Flatten a previously generated summary so its heading is not nested."""
    body = content[len(SUMMARY_TITLE) :].lstrip()
    if body.startswith(SUMMARY_INTRO):
        body = body[len(SUMMARY_INTRO) :].lstrip()
    return body.replace(SUMMARY_TITLE, "").strip()


def build_summary(
    messages: List[Dict[str, str]],
    config: ContextConfig,
) -> str:
    """Build a deterministic summary in original chronological order."""
    lines = [SUMMARY_TITLE, SUMMARY_INTRO]
    next_number = 1

    for message in messages:
        content = message["content"].strip()
        if message["role"] == "assistant" and content.startswith(SUMMARY_TITLE):
            body = _existing_summary_body(content)
            if body:
                lines.append(body)
                numbers = [
                    int(match.group(1))
                    for match in re.finditer(r"(?m)^(\d+)\.", body)
                ]
                if numbers:
                    next_number = max(numbers) + 1
            continue

        shortened = truncate_text(
            content,
            config.per_message_chars,
            MESSAGE_TRUNCATION_MARKER,
        )
        role_label = "用户" if message["role"] == "user" else "助手"
        lines.append("{}. {}：{}".format(next_number, role_label, shortened))
        next_number += 1

    raw_summary = "\n".join(lines)
    return truncate_text(
        raw_summary,
        config.summary_max_chars,
        SUMMARY_TRUNCATION_MARKER,
    )


class BasicContextManager:
    """Normalize and deterministically compress recalled Session history."""

    def __init__(self, config: Optional[ContextConfig] = None) -> None:
        if config is not None and not isinstance(config, ContextConfig):
            raise ValueError("config must be a ContextConfig or None.")
        self.config = config if config is not None else ContextConfig()

    def build(self, history: List[Any]) -> ContextBuildResult:
        """Build Runtime-ready history without changing any caller-owned value."""
        messages = normalize_history(history)
        original_count = len(messages)
        original_chars = estimate_messages_chars(messages)
        should_compress = (
            original_count > self.config.max_messages
            or original_chars > self.config.max_chars
        )

        if not should_compress:
            output = [dict(message) for message in messages]
            return ContextBuildResult(
                messages=output,
                compressed=False,
                original_message_count=original_count,
                output_message_count=len(output),
                summarized_message_count=0,
                retained_recent_count=original_count,
                original_char_count=original_chars,
                output_char_count=estimate_messages_chars(output),
                summary_text=None,
            )

        has_existing_summary = bool(
            messages
            and messages[0]["role"] == "assistant"
            and messages[0]["content"].startswith(SUMMARY_TITLE)
        )
        recalled = messages[1:] if has_existing_summary else messages
        retained_count = min(self.config.recent_messages, len(recalled))
        split_at = len(recalled) - retained_count
        older = [dict(message) for message in recalled[:split_at]]
        if has_existing_summary:
            older.insert(0, dict(messages[0]))
        recent = [dict(message) for message in recalled[split_at:]]

        summary = build_summary(older, self.config)
        output = [{"role": "assistant", "content": summary}] + recent
        self._fit_to_character_limit(output)
        summary = output[0]["content"]
        output_chars = estimate_messages_chars(output)

        return ContextBuildResult(
            messages=output,
            compressed=True,
            original_message_count=original_count,
            output_message_count=len(output),
            summarized_message_count=len(older),
            retained_recent_count=len(recent),
            original_char_count=original_chars,
            output_char_count=output_chars,
            summary_text=summary,
        )

    def _fit_to_character_limit(self, messages: List[Dict[str, str]]) -> None:
        """Shorten the summary, then older recent messages, until budgeted."""
        excess = estimate_messages_chars(messages) - self.config.max_chars
        if excess <= 0:
            return

        summary_content = messages[0]["content"]
        minimum_summary_chars = min(len(summary_content), len(SUMMARY_TITLE))
        summary_target = max(
            minimum_summary_chars,
            len(summary_content) - excess,
        )
        messages[0]["content"] = truncate_text(
            summary_content,
            summary_target,
            SUMMARY_TRUNCATION_MARKER,
        )

        # Old-to-new traversal preserves as much of the newest history as possible.
        for message in messages[1:]:
            excess = estimate_messages_chars(messages) - self.config.max_chars
            if excess <= 0:
                break
            content = message["content"]
            target = max(1, len(content) - excess)
            message["content"] = truncate_text(
                content,
                target,
                CONTEXT_TRUNCATION_MARKER,
            )

        # Only sacrifice the recognizable summary title when even one character
        # per message plus structural overhead cannot fit the configured budget.
        excess = estimate_messages_chars(messages) - self.config.max_chars
        if excess > 0 and len(messages[0]["content"]) > 1:
            content = messages[0]["content"]
            target = max(1, len(content) - excess)
            messages[0]["content"] = truncate_text(
                content,
                target,
                SUMMARY_TRUNCATION_MARKER,
            )


__all__ = [
    "ContextConfig",
    "ContextBuildResult",
    "ContextCompressionError",
    "BasicContextManager",
    "estimate_messages_chars",
]

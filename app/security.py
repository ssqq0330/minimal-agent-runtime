"""Shared redaction helpers for client-visible errors and persisted diagnostics."""

from __future__ import annotations

import re
from typing import Any


ERROR_TRUNCATION_MARKER = "… [truncated]"

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b(LLM_API_KEY|API[_-]?KEY|Authorization|password|secret|"
    r"access[_-]?token|refresh[_-]?token)\b\s*[:=]\s*"
    r"(?:Bearer\s+)?(?:[\"']?)[^\s,;\"'<>}]+"
)
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_ENV_LINE = re.compile(
    r"(?im)^\s*(?:export\s+)?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET)"
    r"\s*=\s*.*$"
)


def sanitize_error_message(message: str, max_chars: int = 1000) -> str:
    """Return a bounded redacted copy without mutating the originating error."""
    if not isinstance(message, str):
        message = str(message) if message is not None else ""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1:
        raise ValueError("max_chars must be a positive integer.")

    sanitized = _ENV_LINE.sub("[REDACTED ENV VALUE]", message)
    sanitized = _SENSITIVE_ASSIGNMENT.sub(
        lambda match: "{}=[REDACTED]".format(match.group(1)),
        sanitized,
    )
    sanitized = _BEARER_TOKEN.sub("Bearer [REDACTED]", sanitized)
    sanitized = sanitized.replace("Traceback (most recent call last):", "[TRACEBACK REDACTED]")
    sanitized = sanitized.strip() or "An internal error occurred."

    if len(sanitized) <= max_chars:
        return sanitized
    if max_chars <= len(ERROR_TRUNCATION_MARKER):
        return sanitized[:max_chars]
    return sanitized[: max_chars - len(ERROR_TRUNCATION_MARKER)].rstrip() + (
        ERROR_TRUNCATION_MARKER
    )


def sanitized_exception_message(error: BaseException, max_chars: int = 1000) -> str:
    """Return a safe message for an exception without modifying the exception."""
    if not isinstance(error, BaseException):
        raise TypeError("error must be an exception.")
    return sanitize_error_message(str(error) or error.__class__.__name__, max_chars)


__all__ = ["sanitize_error_message", "sanitized_exception_message"]

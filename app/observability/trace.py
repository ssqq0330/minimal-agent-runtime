"""Persistent, sanitized execution Trace records for Session Agent runs."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.memory.context import ContextBuildResult
from app.memory.store import MemoryStoreError, SQLiteStore
from app.security import sanitize_error_message

if TYPE_CHECKING:
    from app.agent.runtime import AgentRunResult


TRACE_TRUNCATION_MARKER = "……[trace 已截断]"
TRACE_STATUSES = {"running", "completed", "failed"}
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "llm_api_key",
    "system_prompt",
    "raw_response",
    "http_response",
    "chain_of_thought",
    "hidden_reasoning",
    "internal_reasoning",
}


class TraceError(Exception):
    """Base exception for Trace validation and persistence failures."""


class TraceValidationError(TraceError, ValueError):
    """Raised when a Trace operation receives invalid input or state."""


class TraceNotFoundError(TraceError):
    """Raised when a requested Trace run does not exist."""


class TracePersistenceError(TraceError):
    """Raised when Trace data cannot be persisted or read."""


@dataclass
class TraceRunRecord:
    run_id: str
    user_id: str
    session_id: str
    status: str
    user_input: str
    final_answer: Optional[str]
    error_type: Optional[str]
    error_message: Optional[str]
    total_llm_calls: int
    total_tool_calls: int
    started_at: str
    finished_at: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "status": self.status,
            "user_input": self.user_input,
            "final_answer": self.final_answer,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


@dataclass
class TraceEventRecord:
    id: int
    run_id: str
    sequence: int
    event_type: str
    step_number: Optional[int]
    payload: Dict[str, Any]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "event_type": self.event_type,
            "step_number": self.step_number,
            "payload": sanitize_trace_payload(self.payload),
            "created_at": self.created_at,
        }


@dataclass
class AgentTraceResult:
    run: TraceRunRecord
    events: List[TraceEventRecord]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "events": [event.to_dict() for event in self.events],
        }


def sanitize_trace_payload(value: Any, max_string_chars: int = 4000) -> Any:
    """Recursively copy, redact, and bound one Trace payload value."""
    if (
        not isinstance(max_string_chars, int)
        or isinstance(max_string_chars, bool)
        or max_string_chars <= 0
    ):
        raise TraceValidationError("max_string_chars must be a positive integer.")
    return _sanitize_value(value, max_string_chars)


def _sanitize_value(value: Any, max_string_chars: int) -> Any:
    if isinstance(value, dict):
        result: Dict[Any, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and key.lower() in SENSITIVE_KEYS:
                result[key] = "[REDACTED]"
            else:
                result[key] = _sanitize_value(item, max_string_chars)
        return result
    if isinstance(value, list):
        return [_sanitize_value(item, max_string_chars) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(item, max_string_chars) for item in value)
    if isinstance(value, str):
        return _sanitize_string(value, max_string_chars)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise TraceValidationError(
        "Trace payload values must be JSON-compatible primitive containers."
    )


def _sanitize_string(value: str, max_chars: int) -> str:
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|llm_api_key|authorization|access_token|"
        r"refresh_token|password|secret|token|system[_ -]?prompt|"
        r"raw[_ -]?(?:http[_ -]?)?response|chain[_ -]?of[_ -]?thought|"
        r"hidden[_ -]?reasoning)\b[\"']?\s*[:=]\s*[\"']?"
        r"(?:Bearer\s+)?[^\s\"',;}\]]+",
        lambda match: "{}=[REDACTED]".format(match.group(1)),
        value,
    )
    redacted = re.sub(
        r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+",
        "Bearer [REDACTED]",
        redacted,
    )
    if len(redacted) <= max_chars:
        return redacted
    if max_chars <= len(TRACE_TRUNCATION_MARKER):
        return redacted[:max_chars]
    return redacted[: max_chars - len(TRACE_TRUNCATION_MARKER)].rstrip() + (
        TRACE_TRUNCATION_MARKER
    )


class SQLiteTraceRecorder:
    """Record sanitized Agent execution events through SQLiteStore APIs."""

    def __init__(self, store: SQLiteStore) -> None:
        if not isinstance(store, SQLiteStore):
            raise TypeError("store must be a SQLiteStore.")
        self.store = store

    def start_run(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
    ) -> TraceRunRecord:
        user_id = self._validate_text(user_id, "user_id")
        session_id = self._validate_text(session_id, "session_id")
        user_input = self._validate_text(user_input, "user_input")
        try:
            session = self.store.get_session(user_id, session_id)
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to verify the Trace Session.") from error
        if session is None:
            raise TraceValidationError("Session does not exist for this user.")
        safe_input = sanitize_trace_payload(user_input, max_string_chars=8000)
        try:
            value = self.store.create_trace_run(
                uuid.uuid4().hex,
                user_id,
                session_id,
                safe_input,
            )
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to start the Trace run.") from error
        return self._run_record(value)

    def record_context(
        self,
        run_id: str,
        context_result: ContextBuildResult,
    ) -> TraceEventRecord:
        if not isinstance(context_result, ContextBuildResult):
            raise TraceValidationError(
                "context_result must be a ContextBuildResult."
            )
        self._require_running(run_id)
        payload = {
            "compressed": context_result.compressed,
            "original_message_count": context_result.original_message_count,
            "output_message_count": context_result.output_message_count,
            "summarized_message_count": context_result.summarized_message_count,
            "retained_recent_count": context_result.retained_recent_count,
            "original_char_count": context_result.original_char_count,
            "output_char_count": context_result.output_char_count,
        }
        return self._append_event(run_id, "context_built", payload)

    def record_agent_result(
        self,
        run_id: str,
        agent_result: AgentRunResult,
    ) -> TraceRunRecord:
        from app.agent.runtime import AgentRunResult as RuntimeAgentRunResult

        if not isinstance(agent_result, RuntimeAgentRunResult):
            raise TraceValidationError("agent_result must be an AgentRunResult.")
        self._require_running(run_id)

        for step in agent_result.steps:
            self._append_event(
                run_id,
                "llm_decision",
                {
                    "decision_type": step.decision_type,
                    "reasoning_summary": step.reasoning_summary,
                    "model": step.model,
                },
                step.step_number,
            )
            results_by_id = {
                result.get("tool_call_id"): result
                for result in step.tool_results
                if isinstance(result, dict)
            }
            for index, tool_call in enumerate(step.tool_calls):
                call_id = tool_call.get("id")
                tool_name = tool_call.get("name")
                self._append_event(
                    run_id,
                    "tool_call",
                    {
                        "tool_call_id": call_id,
                        "tool_name": tool_name,
                        "arguments": tool_call.get("arguments", {}),
                    },
                    step.step_number,
                )
                result_record = results_by_id.get(call_id)
                if result_record is None and index < len(step.tool_results):
                    result_record = step.tool_results[index]
                result_value = (
                    result_record.get("result", {})
                    if isinstance(result_record, dict)
                    else {}
                )
                if not isinstance(result_value, dict):
                    result_value = {
                        "success": False,
                        "output": None,
                        "error": "Tool result had an invalid shape.",
                    }
                self._append_event(
                    run_id,
                    "tool_result",
                    {
                        "tool_call_id": call_id,
                        "tool_name": tool_name,
                        "success": bool(result_value.get("success", False)),
                        "output": result_value.get("output"),
                        "error": result_value.get("error"),
                    },
                    step.step_number,
                )

        self._append_event(
            run_id,
            "run_completed",
            {
                "stopped_reason": agent_result.stopped_reason,
                "total_llm_calls": agent_result.total_llm_calls,
                "total_tool_calls": agent_result.total_tool_calls,
            },
        )
        final_answer = sanitize_trace_payload(
            agent_result.answer,
            max_string_chars=8000,
        )
        try:
            value = self.store.update_trace_run_completed(
                run_id,
                final_answer,
                agent_result.total_llm_calls,
                agent_result.total_tool_calls,
            )
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to complete the Trace run.") from error
        if value is None:
            raise TraceValidationError("Trace run is no longer running.")
        return self._run_record(value)

    def fail_run(self, run_id: str, error: Exception) -> TraceRunRecord:
        if not isinstance(error, Exception):
            raise TraceValidationError("error must be an Exception.")
        self._require_running(run_id)
        error_type = error.__class__.__name__
        error_message = sanitize_error_message(
            str(error).strip() or "Error without a message.",
            max_chars=1000,
        )
        self._append_event(
            run_id,
            "run_failed",
            {"error_type": error_type, "error_message": error_message},
        )
        try:
            value = self.store.update_trace_run_failed(
                run_id,
                error_type,
                error_message,
            )
        except (MemoryStoreError, ValueError) as persistence_error:
            raise TracePersistenceError("Failed to fail the Trace run.") from (
                persistence_error
            )
        if value is None:
            raise TraceValidationError("Trace run is no longer running.")
        return self._run_record(value)

    def get_trace(self, run_id: str) -> AgentTraceResult:
        run_id = self._validate_text(run_id, "run_id")
        try:
            run_value = self.store.get_trace_run(run_id)
            if run_value is None:
                raise TraceNotFoundError("Trace run was not found.")
            event_values = self.store.list_trace_events(run_id)
        except TraceNotFoundError:
            raise
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to read the Trace.") from error
        return AgentTraceResult(
            run=self._run_record(run_value),
            events=[self._event_record(value) for value in event_values],
        )

    def list_runs(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[TraceRunRecord]:
        user_id = self._validate_text(user_id, "user_id")
        if session_id is not None:
            session_id = self._validate_text(session_id, "session_id")
        if status is not None:
            if not isinstance(status, str) or status not in TRACE_STATUSES:
                raise TraceValidationError(
                    "status must be 'running', 'completed', or 'failed'."
                )
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > 200
        ):
            raise TraceValidationError("limit must be an integer from 1 to 200.")
        try:
            values = self.store.list_trace_runs(
                user_id,
                session_id=session_id,
                status=status,
                limit=limit,
            )
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to list Trace runs.") from error
        return [self._run_record(value) for value in values]

    def delete_trace(self, user_id: str, run_id: str) -> bool:
        user_id = self._validate_text(user_id, "user_id")
        run_id = self._validate_text(run_id, "run_id")
        try:
            return self.store.delete_trace_run(user_id, run_id)
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to delete the Trace.") from error

    def _append_event(
        self,
        run_id: str,
        event_type: str,
        payload: Dict[str, Any],
        step_number: Optional[int] = None,
    ) -> TraceEventRecord:
        safe_payload = sanitize_trace_payload(payload)
        try:
            value = self.store.append_trace_event(
                run_id,
                event_type,
                safe_payload,
                step_number=step_number,
            )
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to append the Trace event.") from error
        return self._event_record(value)

    def _require_running(self, run_id: str) -> TraceRunRecord:
        run_id = self._validate_text(run_id, "run_id")
        try:
            value = self.store.get_trace_run(run_id)
        except (MemoryStoreError, ValueError) as error:
            raise TracePersistenceError("Failed to read the Trace run.") from error
        if value is None:
            raise TraceNotFoundError("Trace run was not found.")
        record = self._run_record(value)
        if record.status != "running":
            raise TraceValidationError(
                "Trace run has status '{}' and is no longer running.".format(
                    record.status
                )
            )
        return record

    @staticmethod
    def _validate_text(value: Any, field_name: str) -> str:
        if not isinstance(value, str):
            raise TraceValidationError("{} must be a string.".format(field_name))
        value = value.strip()
        if not value:
            raise TraceValidationError("{} must not be empty.".format(field_name))
        if field_name in {"user_id", "session_id"} and len(value) > 128:
            raise TraceValidationError(
                "{} must not exceed 128 characters.".format(field_name)
            )
        return value

    @staticmethod
    def _run_record(value: Dict[str, Any]) -> TraceRunRecord:
        return TraceRunRecord(**value)

    @staticmethod
    def _event_record(value: Dict[str, Any]) -> TraceEventRecord:
        return TraceEventRecord(**value)


__all__ = [
    "TraceRunRecord",
    "TraceEventRecord",
    "AgentTraceResult",
    "TraceError",
    "TraceValidationError",
    "TraceNotFoundError",
    "TracePersistenceError",
    "SQLiteTraceRecorder",
    "sanitize_trace_payload",
]

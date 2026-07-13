"""Connect persisted Session history to the stateless Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.runtime import AgentRunResult, AgentRuntime
from app.agent.session_locks import SessionLockManager
from app.memory.context import BasicContextManager, ContextBuildResult
from app.memory.store import (
    MessageRecord,
    SessionNotFoundError,
    SessionRecord,
    SQLiteStore,
)
from app.observability.trace import SQLiteTraceRecorder, TraceError
from app.tools.base import ToolContext


@dataclass
class SessionChatResult:
    """One successful Runtime result together with its persisted exchange."""

    session: SessionRecord
    user_message: MessageRecord
    assistant_message: MessageRecord
    agent_result: AgentRunResult
    loaded_history_count: int
    context_result: Optional[ContextBuildResult] = None
    run_id: Optional[str] = None

    @property
    def context_compressed(self) -> bool:
        """Whether recalled history was compressed for this Runtime call."""
        return bool(self.context_result and self.context_result.compressed)

    @property
    def context_message_count(self) -> int:
        """Return the number of history messages supplied to the Runtime."""
        if self.context_result is None:
            return self.loaded_history_count
        return self.context_result.output_message_count

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable view suitable for a future HTTP API."""
        return {
            "session": self.session.to_dict(),
            "user_message": self.user_message.to_dict(),
            "assistant_message": self.assistant_message.to_dict(),
            "agent_result": self.agent_result.to_dict(),
            "loaded_history_count": self.loaded_history_count,
            "context": self._context_stats(),
            "run_id": self.run_id,
        }

    def _context_stats(self) -> Dict[str, Any]:
        if self.context_result is None:
            return {
                "compressed": False,
                "original_message_count": self.loaded_history_count,
                "output_message_count": self.loaded_history_count,
                "summarized_message_count": 0,
                "retained_recent_count": self.loaded_history_count,
                "original_char_count": 0,
                "output_char_count": 0,
            }
        return _context_stats(self.context_result)


class SessionAgentService:
    """Load natural-language history, run the Agent, and persist the exchange."""

    def __init__(
        self,
        runtime: AgentRuntime,
        store: SQLiteStore,
        history_limit: Optional[int] = None,
        context_manager: Optional[BasicContextManager] = None,
        trace_recorder: Optional[SQLiteTraceRecorder] = None,
        lock_manager: Optional[SessionLockManager] = None,
    ) -> None:
        if not isinstance(runtime, AgentRuntime):
            raise ValueError("runtime must be an AgentRuntime.")
        if not isinstance(store, SQLiteStore):
            raise ValueError("store must be a SQLiteStore.")
        if context_manager is not None and not isinstance(
            context_manager,
            BasicContextManager,
        ):
            raise TypeError("context_manager must be a BasicContextManager or None.")
        if trace_recorder is not None and not isinstance(
            trace_recorder,
            SQLiteTraceRecorder,
        ):
            raise TypeError("trace_recorder must be a SQLiteTraceRecorder or None.")
        if lock_manager is not None and not isinstance(lock_manager, SessionLockManager):
            raise TypeError("lock_manager must be a SessionLockManager or None.")
        self._validate_limit(history_limit, "history_limit")
        self.runtime = runtime
        self.store = store
        self.history_limit = history_limit
        self.context_manager = (
            context_manager
            if context_manager is not None
            else BasicContextManager()
        )
        self.trace_recorder = (
            trace_recorder
            if trace_recorder is not None
            else SQLiteTraceRecorder(store)
        )
        self.lock_manager = lock_manager or SessionLockManager()

    def chat(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
    ) -> SessionChatResult:
        """Run one Session turn and atomically persist it after Runtime success."""
        user_id = self._validate_text(user_id, "user_id", max_chars=128)
        session_id = self._validate_text(session_id, "session_id", max_chars=128)
        user_input = self._validate_text(user_input, "user_input", max_chars=8000)
        with self.lock_manager.acquire(user_id, session_id):
            return self._chat_locked(user_id, session_id, user_input)

    def _chat_locked(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
    ) -> SessionChatResult:
        """Execute the full stateful turn while its Session lock is held."""
        self._require_session(user_id, session_id)
        trace_run = self.trace_recorder.start_run(user_id, session_id, user_input)

        try:
            raw_history = self.store.list_messages(
                user_id,
                session_id,
                limit=self.history_limit,
            )
            context_result = self.context_manager.build(raw_history)
            self.trace_recorder.record_context(trace_run.run_id, context_result)
            context = ToolContext(user_id=user_id, session_id=session_id)
            agent_result = self.runtime.run(
                user_input=user_input,
                context=context,
                history=context_result.messages,
            )

            user_message, assistant_message = self.store.add_exchange(
                user_id=user_id,
                session_id=session_id,
                user_content=user_input,
                assistant_content=agent_result.answer,
                assistant_metadata=self._build_agent_metadata(
                    agent_result,
                    context_result,
                ),
            )
            self.trace_recorder.record_agent_result(trace_run.run_id, agent_result)
            updated_session = self.store.get_session(user_id, session_id)
            if updated_session is None:
                raise SessionNotFoundError(
                    "Session '{}' no longer exists for this user.".format(session_id)
                )

            return SessionChatResult(
                session=updated_session,
                user_message=user_message,
                assistant_message=assistant_message,
                agent_result=agent_result,
                loaded_history_count=len(raw_history),
                context_result=context_result,
                run_id=trace_run.run_id,
            )
        except Exception as error:
            try:
                self.trace_recorder.fail_run(trace_run.run_id, error)
            except TraceError as trace_error:
                raise trace_error from error
            raise

    def get_history(
        self,
        user_id: str,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[MessageRecord]:
        """Return one existing Session's messages from oldest to newest."""
        user_id = self._validate_text(user_id, "user_id")
        session_id = self._validate_text(session_id, "session_id")
        self._validate_limit(limit, "limit")
        self._require_session(user_id, session_id)
        return self.store.list_messages(user_id, session_id, limit=limit)

    def clear_history(self, user_id: str, session_id: str) -> int:
        """Clear only messages for one existing Session, retaining its Todos."""
        user_id = self._validate_text(user_id, "user_id")
        session_id = self._validate_text(session_id, "session_id")
        self._require_session(user_id, session_id)
        return self.store.clear_messages(user_id, session_id)

    def _require_session(self, user_id: str, session_id: str) -> SessionRecord:
        session = self.store.get_session(user_id, session_id)
        if session is None:
            raise SessionNotFoundError(
                "Session '{}' does not exist for this user.".format(session_id)
            )
        return session

    @staticmethod
    def _build_agent_metadata(
        agent_result: AgentRunResult,
        context_result: ContextBuildResult,
    ) -> Dict[str, Any]:
        used_tools: List[str] = []
        reasoning_summaries: List[str] = []
        for step in agent_result.steps:
            if step.reasoning_summary:
                reasoning_summaries.append(step.reasoning_summary)
            for tool_call in step.tool_calls:
                tool_name = tool_call.get("name")
                if isinstance(tool_name, str) and tool_name not in used_tools:
                    used_tools.append(tool_name)

        return {
            "agent": {
                "total_llm_calls": agent_result.total_llm_calls,
                "total_tool_calls": agent_result.total_tool_calls,
                "stopped_reason": agent_result.stopped_reason,
                "used_tools": used_tools,
                "reasoning_summaries": reasoning_summaries,
            },
            "context": _context_stats(context_result),
        }

    @staticmethod
    def _validate_text(
        value: Any,
        field_name: str,
        max_chars: Optional[int] = None,
    ) -> str:
        if not isinstance(value, str):
            raise ValueError("{} must be a string.".format(field_name))
        value = value.strip()
        if not value:
            raise ValueError("{} must not be empty.".format(field_name))
        if max_chars is not None and len(value) > max_chars:
            raise ValueError(
                "{} must not exceed {} characters.".format(field_name, max_chars)
            )
        return value

    @staticmethod
    def _validate_limit(value: Optional[int], field_name: str) -> None:
        if value is None:
            return
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value <= 0
            or value > 500
        ):
            raise ValueError("{} must be an integer from 1 to 500.".format(field_name))


def _context_stats(context_result: ContextBuildResult) -> Dict[str, Any]:
    """Return only safe, compact Context statistics for results and metadata."""
    return {
        "compressed": context_result.compressed,
        "original_message_count": context_result.original_message_count,
        "output_message_count": context_result.output_message_count,
        "summarized_message_count": context_result.summarized_message_count,
        "retained_recent_count": context_result.retained_recent_count,
        "original_char_count": context_result.original_char_count,
        "output_char_count": context_result.output_char_count,
    }

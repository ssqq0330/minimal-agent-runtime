"""Connect persisted Session history to the stateless Agent Runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.runtime import AgentRunResult, AgentRuntime
from app.memory.store import (
    MessageRecord,
    SessionNotFoundError,
    SessionRecord,
    SQLiteStore,
)
from app.tools.base import ToolContext


@dataclass
class SessionChatResult:
    """One successful Runtime result together with its persisted exchange."""

    session: SessionRecord
    user_message: MessageRecord
    assistant_message: MessageRecord
    agent_result: AgentRunResult
    loaded_history_count: int

    def to_dict(self) -> Dict[str, Any]:
        """Return a serializable view suitable for a future HTTP API."""
        return {
            "session": self.session.to_dict(),
            "user_message": self.user_message.to_dict(),
            "assistant_message": self.assistant_message.to_dict(),
            "agent_result": self.agent_result.to_dict(),
            "loaded_history_count": self.loaded_history_count,
        }


class SessionAgentService:
    """Load natural-language history, run the Agent, and persist the exchange."""

    def __init__(
        self,
        runtime: AgentRuntime,
        store: SQLiteStore,
        history_limit: Optional[int] = None,
    ) -> None:
        if not isinstance(runtime, AgentRuntime):
            raise ValueError("runtime must be an AgentRuntime.")
        if not isinstance(store, SQLiteStore):
            raise ValueError("store must be a SQLiteStore.")
        self._validate_limit(history_limit, "history_limit")
        self.runtime = runtime
        self.store = store
        self.history_limit = history_limit

    def chat(
        self,
        user_id: str,
        session_id: str,
        user_input: str,
    ) -> SessionChatResult:
        """Run one Session turn and atomically persist it after Runtime success."""
        user_id = self._validate_text(user_id, "user_id")
        session_id = self._validate_text(session_id, "session_id")
        user_input = self._validate_text(user_input, "user_input")
        self._require_session(user_id, session_id)

        stored_history = self.store.list_messages(
            user_id,
            session_id,
            limit=self.history_limit,
        )
        history = [
            {"role": message.role, "content": message.content}
            for message in stored_history
            if message.role in {"user", "assistant"}
        ]
        context = ToolContext(user_id=user_id, session_id=session_id)
        agent_result = self.runtime.run(
            user_input=user_input,
            context=context,
            history=history,
        )

        user_message, assistant_message = self.store.add_exchange(
            user_id=user_id,
            session_id=session_id,
            user_content=user_input,
            assistant_content=agent_result.answer,
            assistant_metadata=self._build_agent_metadata(agent_result),
        )
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
            loaded_history_count=len(history),
        )

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
    def _build_agent_metadata(agent_result: AgentRunResult) -> Dict[str, Any]:
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
            }
        }

    @staticmethod
    def _validate_text(value: Any, field_name: str) -> str:
        if not isinstance(value, str):
            raise ValueError("{} must be a string.".format(field_name))
        value = value.strip()
        if not value:
            raise ValueError("{} must not be empty.".format(field_name))
        return value

    @staticmethod
    def _validate_limit(value: Optional[int], field_name: str) -> None:
        if value is None:
            return
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError("{} must be an integer greater than 0.".format(field_name))

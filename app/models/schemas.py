"""Validated HTTP request and compact response schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class _TrimmedModel(BaseModel):
    @field_validator("*", mode="before")
    @classmethod
    def trim_strings(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class CreateSessionRequest(_TrimmedModel):
    user_id: str = Field(min_length=1, max_length=128)
    session_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    title: str = Field(default="新会话", min_length=1, max_length=200)


class UpdateSessionRequest(_TrimmedModel):
    user_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=200)


class ChatRequest(_TrimmedModel):
    user_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=8000)


class SessionResponse(BaseModel):
    user_id: str
    session_id: str
    title: str
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: str
    metadata: Optional[Dict[str, Any]] = None


class ContextStatsResponse(BaseModel):
    compressed: bool
    original_message_count: int
    output_message_count: int
    summarized_message_count: int
    retained_recent_count: int
    original_char_count: int
    output_char_count: int


class AgentStatsResponse(BaseModel):
    total_llm_calls: int
    total_tool_calls: int
    stopped_reason: str


class ChatResponse(BaseModel):
    session: SessionResponse
    user_message: MessageResponse
    assistant_message: MessageResponse
    answer: str
    run_id: str
    loaded_history_count: int
    context: ContextStatsResponse
    agent: AgentStatsResponse


class TraceRunResponse(BaseModel):
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


class TraceEventResponse(BaseModel):
    id: int
    run_id: str
    sequence: int
    event_type: str
    step_number: Optional[int]
    payload: Dict[str, Any]
    created_at: str


class TraceDetailResponse(BaseModel):
    run: TraceRunResponse
    events: List[TraceEventResponse]


class TodoResponse(BaseModel):
    id: int
    content: str
    completed: bool
    created_at: str
    completed_at: Optional[str]


class DeletedCountResponse(BaseModel):
    deleted_count: int


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


__all__ = [
    "CreateSessionRequest",
    "UpdateSessionRequest",
    "ChatRequest",
    "SessionResponse",
    "MessageResponse",
    "ContextStatsResponse",
    "AgentStatsResponse",
    "ChatResponse",
    "TraceRunResponse",
    "TraceEventResponse",
    "TraceDetailResponse",
    "TodoResponse",
    "DeletedCountResponse",
    "ErrorResponse",
]

"""Compact Session Agent chat HTTP route."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.dependencies import ApplicationServices, get_application_services
from app.models.schemas import ChatRequest, ChatResponse


router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    services: ApplicationServices = Depends(get_application_services),
) -> dict:
    result = services.require_session_service().chat(
        request.user_id,
        request.session_id,
        request.message,
    )
    if result.run_id is None:
        raise RuntimeError("Successful chat did not return run_id.")
    context = result.to_dict()["context"]
    return {
        "session": result.session.to_dict(),
        "user_message": _message_response(result.user_message),
        "assistant_message": _message_response(result.assistant_message),
        "answer": result.agent_result.answer,
        "run_id": result.run_id,
        "loaded_history_count": result.loaded_history_count,
        "context": context,
        "agent": {
            "total_llm_calls": result.agent_result.total_llm_calls,
            "total_tool_calls": result.agent_result.total_tool_calls,
            "stopped_reason": result.agent_result.stopped_reason,
        },
    }


def _message_response(record) -> dict:
    return {
        "id": record.id,
        "role": record.role,
        "content": record.content,
        "created_at": record.created_at,
        "metadata": record.metadata,
    }


__all__ = ["router"]

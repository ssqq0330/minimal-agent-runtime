"""Session, message-history, and Session-scoped Todo HTTP routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.dependencies import ApplicationServices, get_application_services
from app.memory import SessionNotFoundError
from app.models.schemas import (
    CreateSessionRequest,
    DeletedCountResponse,
    MessageResponse,
    SessionResponse,
    TodoResponse,
    UpdateSessionRequest,
)


router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    request: CreateSessionRequest,
    services: ApplicationServices = Depends(get_application_services),
) -> dict:
    record = services.store.create_session(
        request.user_id,
        request.session_id,
        request.title,
    )
    return record.to_dict()


@router.get("", response_model=List[SessionResponse])
def list_sessions(
    user_id: str = Query(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> list[dict]:
    return [record.to_dict() for record in services.store.list_sessions(user_id)]


@router.get("/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str = Path(min_length=1, max_length=128),
    user_id: str = Query(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> dict:
    return _require_session(services, user_id, session_id).to_dict()


@router.patch("/{session_id}", response_model=SessionResponse)
def update_session(
    request: UpdateSessionRequest,
    session_id: str = Path(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> dict:
    return services.store.update_session_title(
        request.user_id,
        session_id,
        request.title,
    ).to_dict()


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str = Path(min_length=1, max_length=128),
    user_id: str = Query(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> Response:
    if not services.store.delete_session(user_id, session_id):
        raise SessionNotFoundError("Session does not exist for this user.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{session_id}/messages", response_model=List[MessageResponse])
def list_messages(
    session_id: str = Path(min_length=1, max_length=128),
    user_id: str = Query(min_length=1, max_length=128),
    limit: int = Query(default=50, ge=1, le=500),
    services: ApplicationServices = Depends(get_application_services),
) -> list[dict]:
    _require_session(services, user_id, session_id)
    return [
        _message_response(record)
        for record in services.store.list_messages(user_id, session_id, limit=limit)
    ]


@router.delete(
    "/{session_id}/messages",
    response_model=DeletedCountResponse,
)
def clear_messages(
    session_id: str = Path(min_length=1, max_length=128),
    user_id: str = Query(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> dict:
    _require_session(services, user_id, session_id)
    return {"deleted_count": services.store.clear_messages(user_id, session_id)}


@router.get("/{session_id}/todos", response_model=List[TodoResponse])
def list_todos(
    session_id: str = Path(min_length=1, max_length=128),
    user_id: str = Query(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> list[dict]:
    _require_session(services, user_id, session_id)
    return [
        {
            "id": record.id,
            "content": record.content,
            "completed": record.completed,
            "created_at": record.created_at,
            "completed_at": record.completed_at,
        }
        for record in services.store.list_todos(user_id, session_id)
    ]


def _require_session(
    services: ApplicationServices,
    user_id: str,
    session_id: str,
):
    record = services.store.get_session(user_id, session_id)
    if record is None:
        raise SessionNotFoundError("Session does not exist for this user.")
    return record


def _message_response(record) -> dict:
    return {
        "id": record.id,
        "role": record.role,
        "content": record.content,
        "created_at": record.created_at,
        "metadata": record.metadata,
    }


__all__ = ["router"]

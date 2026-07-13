"""User-scoped Agent Trace list, detail, and deletion routes."""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.dependencies import ApplicationServices, get_application_services
from app.models.schemas import TraceDetailResponse, TraceRunResponse
from app.observability import TraceNotFoundError


router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("", response_model=List[TraceRunResponse])
def list_traces(
    user_id: str = Query(min_length=1, max_length=128),
    session_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    services: ApplicationServices = Depends(get_application_services),
) -> list[dict]:
    return [
        record.to_dict()
        for record in services.trace_recorder.list_runs(
            user_id,
            session_id=session_id,
            status=status_filter,
            limit=limit,
        )
    ]


@router.get("/{run_id}", response_model=TraceDetailResponse)
def get_trace(
    run_id: str = Path(min_length=1, max_length=128),
    user_id: str = Query(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> dict:
    trace = services.trace_recorder.get_trace(run_id)
    if trace.run.user_id != user_id:
        raise TraceNotFoundError("Trace does not exist for this user.")
    return trace.to_dict()


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_trace(
    run_id: str = Path(min_length=1, max_length=128),
    user_id: str = Query(min_length=1, max_length=128),
    services: ApplicationServices = Depends(get_application_services),
) -> Response:
    if not services.trace_recorder.delete_trace(user_id, run_id):
        raise TraceNotFoundError("Trace does not exist for this user.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]

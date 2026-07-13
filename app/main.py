"""FastAPI application factory and resource lifecycle."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Optional, Union

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.errors import install_exception_handlers
from app.api.sessions import router as sessions_router
from app.api.traces import router as traces_router
from app.dependencies import (
    ApplicationServices,
    create_application_services,
    create_degraded_services,
)
from app.llm import LLMConfigurationError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"


def create_app(
    services: Optional[ApplicationServices] = None,
    db_path: Union[str, Path] = "data/agent.db",
) -> FastAPI:
    """Create an app with production lifespan or caller-injected services."""
    injected_services = services

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        active_services = injected_services
        if active_services is None:
            try:
                active_services = create_application_services(db_path)
            except LLMConfigurationError:
                active_services = create_degraded_services(db_path)
        application.state.services = active_services
        try:
            yield
        finally:
            active_services.close()

    application = FastAPI(title="Minimal Agent Runtime", lifespan=lifespan)
    if services is not None:
        application.state.services = services

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_exception_handlers(application)
    application.include_router(sessions_router)
    application.include_router(chat_router)
    application.include_router(traces_router)
    application.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @application.get("/", include_in_schema=False)
    def read_index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @application.get("/api/health")
    def health_check(request: Request) -> dict:
        active = getattr(request.app.state, "services", None)
        return {
            "status": "ok",
            "service": "minimal-agent-runtime",
            "llm_configured": bool(
                isinstance(active, ApplicationServices) and active.llm_configured
            ),
            "database": (
                "available" if isinstance(active, ApplicationServices) else "unavailable"
            ),
        }

    return application


app = create_app()


__all__ = ["app", "create_app"]

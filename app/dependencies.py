"""Explicit construction and lifecycle ownership for application services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from fastapi import Request

from app.agent import AgentRuntime, SessionAgentService
from app.llm import LLMConfig, LLMConfigurationError, OpenAICompatibleLLMClient
from app.memory import BasicContextManager, SQLiteStore
from app.observability import SQLiteTraceRecorder
from app.tools import ToolRegistry, create_default_registry


@dataclass
class ApplicationServices:
    """Application-owned services, with optional degraded no-LLM operation."""

    store: SQLiteStore
    context_manager: BasicContextManager
    trace_recorder: SQLiteTraceRecorder
    llm_client: Optional[Any] = None
    tool_registry: Optional[ToolRegistry] = None
    runtime: Optional[AgentRuntime] = None
    session_service: Optional[SessionAgentService] = None
    owns_llm_client: bool = False

    @property
    def llm_configured(self) -> bool:
        return self.llm_client is not None and self.session_service is not None

    def require_session_service(self) -> SessionAgentService:
        if self.session_service is None:
            raise LLMConfigurationError("LLM service is not configured.")
        return self.session_service

    def close(self) -> None:
        """Close only an internally owned LLM client."""
        if not self.owns_llm_client or self.llm_client is None:
            return
        close = getattr(self.llm_client, "close", None)
        if callable(close):
            close()


def create_application_services(
    db_path: Union[str, Path] = "data/agent.db",
) -> ApplicationServices:
    """Create the fully configured production service graph."""
    config = LLMConfig.from_env()
    store = SQLiteStore(db_path)
    client = OpenAICompatibleLLMClient(config)
    registry = create_default_registry(todo_store=store)
    runtime = AgentRuntime(client, registry)
    context_manager = BasicContextManager()
    trace_recorder = SQLiteTraceRecorder(store)
    session_service = SessionAgentService(
        runtime,
        store,
        context_manager=context_manager,
        trace_recorder=trace_recorder,
    )
    return ApplicationServices(
        store=store,
        llm_client=client,
        tool_registry=registry,
        runtime=runtime,
        context_manager=context_manager,
        trace_recorder=trace_recorder,
        session_service=session_service,
        owns_llm_client=True,
    )


def create_degraded_services(
    db_path: Union[str, Path] = "data/agent.db",
) -> ApplicationServices:
    """Create database/Context/Trace services when LLM config is unavailable."""
    store = SQLiteStore(db_path)
    context_manager = BasicContextManager()
    trace_recorder = SQLiteTraceRecorder(store)
    return ApplicationServices(
        store=store,
        context_manager=context_manager,
        trace_recorder=trace_recorder,
    )


def get_application_services(request: Request) -> ApplicationServices:
    """Resolve the service graph injected into the current FastAPI app."""
    services = getattr(request.app.state, "services", None)
    if not isinstance(services, ApplicationServices):
        raise LLMConfigurationError("Application services are unavailable.")
    return services


__all__ = [
    "ApplicationServices",
    "create_application_services",
    "create_degraded_services",
    "get_application_services",
]

"""Shared offline service graph for FastAPI route tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Union

from app.agent import AgentRuntime, SessionAgentService
from app.dependencies import ApplicationServices
from app.llm import LLMResponse
from app.memory import BasicContextManager, ContextConfig, SQLiteStore
from app.observability import SQLiteTraceRecorder
from app.tools import create_default_registry


FakeResponse = Union[str, Exception]


def final_content(
    answer: str = "最终回答",
    reasoning_summary: str = "可以回答。",
) -> str:
    return json.dumps(
        {
            "type": "final",
            "reasoning_summary": reasoning_summary,
            "answer": answer,
        },
        ensure_ascii=False,
    )


def tool_content(calls: List[Dict[str, object]]) -> str:
    return json.dumps(
        {
            "type": "tool_call",
            "reasoning_summary": "需要调用工具。",
            "tool_calls": calls,
        },
        ensure_ascii=False,
    )


class FakeLLMClient:
    def __init__(self, responses: List[FakeResponse]) -> None:
        self.responses = list(responses)
        self.calls: List[List[Dict[str, str]]] = []
        self.closed = False

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        self.calls.append([dict(message) for message in messages])
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return LLMResponse(content=response, model="fake-model")

    def close(self) -> None:
        self.closed = True


def make_test_services(
    tmp_path: Path,
    responses: Optional[List[FakeResponse]] = None,
    context_config: Optional[ContextConfig] = None,
    max_steps: int = 8,
    owns_client: bool = False,
):
    store = SQLiteStore(tmp_path / "api" / "agent.db")
    client = FakeLLMClient(responses or [])
    registry = create_default_registry(todo_store=store)
    runtime = AgentRuntime(client, registry, max_steps=max_steps)  # type: ignore[arg-type]
    manager = BasicContextManager(context_config)
    recorder = SQLiteTraceRecorder(store)
    session_service = SessionAgentService(
        runtime,
        store,
        context_manager=manager,
        trace_recorder=recorder,
    )
    services = ApplicationServices(
        store=store,
        llm_client=client,
        tool_registry=registry,
        runtime=runtime,
        context_manager=manager,
        trace_recorder=recorder,
        session_service=session_service,
        owns_llm_client=owns_client,
    )
    return services, client

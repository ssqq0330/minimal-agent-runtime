"""Concurrency guarantees for Session locks, chat turns, Todos, and Trace events."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

import pytest

from app.agent import AgentLLMError, AgentRuntime, SessionAgentService, SessionLockManager
from app.llm import LLMRequestError, LLMResponse
from app.memory import SQLiteStore
from app.observability import SQLiteTraceRecorder
from app.tools import create_default_registry


def final(answer: str) -> str:
    return json.dumps(
        {"type": "final", "reasoning_summary": "done", "answer": answer}
    )


class ControlledClient:
    def __init__(self, block_first: bool = False, barrier_parties: int = 0) -> None:
        self.calls: List[List[Dict[str, str]]] = []
        self._guard = threading.Lock()
        self.first_entered = threading.Event()
        self.release_first = threading.Event()
        self.block_first = block_first
        self.barrier = (
            threading.Barrier(barrier_parties, timeout=3) if barrier_parties else None
        )

    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        with self._guard:
            index = len(self.calls)
            self.calls.append([dict(item) for item in messages])
        if index == 0 and self.block_first:
            self.first_entered.set()
            assert self.release_first.wait(timeout=3)
        if self.barrier is not None:
            self.barrier.wait()
        prompt = messages[-1]["content"]
        return LLMResponse(content=final("answer:{}".format(prompt)), model="fake")


class FailOnceClient(ControlledClient):
    def complete(self, messages: List[Dict[str, str]]) -> LLMResponse:
        with self._guard:
            index = len(self.calls)
            self.calls.append([dict(item) for item in messages])
        if index == 0:
            raise LLMRequestError("temporary failure")
        return LLMResponse(content=final("recovered"), model="fake")


def make_service(store: SQLiteStore, client: ControlledClient) -> SessionAgentService:
    runtime = AgentRuntime(  # type: ignore[arg-type]
        client,
        create_default_registry(todo_store=store),
    )
    return SessionAgentService(runtime, store)


def test_lock_scope_and_cleanup_are_user_session_specific() -> None:
    manager = SessionLockManager()
    entered = []
    release = threading.Event()

    def hold(user: str, session: str) -> None:
        with manager.acquire(user, session):
            entered.append((user, session))
            release.wait(timeout=2)

    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(hold, "a", "same")
        second = pool.submit(hold, "a", "other")
        third = pool.submit(hold, "b", "same")
        for _ in range(1000):
            if len(entered) == 3:
                break
            threading.Event().wait(0.001)
        assert set(entered) == {("a", "same"), ("a", "other"), ("b", "same")}
        assert manager.active_lock_count == 3
        release.set()
        first.result(timeout=3)
        second.result(timeout=3)
        third.result(timeout=3)
    assert manager.active_lock_count == 0


def test_same_scope_uses_one_serial_lock_and_exception_releases_it() -> None:
    manager = SessionLockManager()
    order = []
    first_inside = threading.Event()
    release = threading.Event()

    def first() -> None:
        with pytest.raises(RuntimeError):
            with manager.acquire("user", "session"):
                order.append("first")
                first_inside.set()
                release.wait(timeout=2)
                raise RuntimeError("boom")

    def second() -> None:
        first_inside.wait(timeout=2)
        with manager.acquire("user", "session"):
            order.append("second")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first)
        second_future = pool.submit(second)
        assert first_inside.wait(timeout=2)
        assert order == ["first"]
        release.set()
        first_future.result(timeout=3)
        second_future.result(timeout=3)
    assert order == ["first", "second"]
    assert manager.active_lock_count == 0


def test_same_session_concurrent_chat_is_serial_and_second_sees_first(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "same-session.db")
    store.create_session("user", "window")
    client = ControlledClient(block_first=True)
    service = make_service(store, client)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.chat, "user", "window", "first")
        assert client.first_entered.wait(timeout=2)
        second = pool.submit(service.chat, "user", "window", "second")
        threading.Event().wait(0.05)
        assert len(client.calls) == 1
        client.release_first.set()
        first_result = first.result(timeout=3)
        second_result = second.result(timeout=3)

    assert first_result.run_id != second_result.run_id
    assert [item.content for item in store.list_messages("user", "window")] == [
        "first", "answer:first", "second", "answer:second"
    ]
    recalled = client.calls[1]
    assert {item["content"] for item in recalled} >= {"first", "answer:first", "second"}
    assert [item.role for item in store.list_messages("user", "window")] == [
        "user", "assistant", "user", "assistant"
    ]


@pytest.mark.parametrize(
    "scopes",
    [(("user", "one"), ("user", "two")), (("a", "same"), ("b", "same"))],
)
def test_different_scopes_can_run_in_parallel(tmp_path: Path, scopes) -> None:
    store = SQLiteStore(tmp_path / (scopes[0][0] + scopes[1][0] + ".db"))
    for user_id, session_id in scopes:
        store.create_session(user_id, session_id)
    client = ControlledClient(barrier_parties=2)
    service = make_service(store, client)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(service.chat, user, session, "hello")
            for user, session in scopes
        ]
        results = [future.result(timeout=4) for future in futures]
    assert len({result.run_id for result in results}) == 2


def test_failed_chat_does_not_hold_session_lock(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "failure.db")
    store.create_session("user", "window")
    client = FailOnceClient()
    service = make_service(store, client)
    with pytest.raises(AgentLLMError):
        service.chat("user", "window", "fail")
    result = service.chat("user", "window", "retry")
    assert result.agent_result.answer == "recovered"
    assert service.lock_manager.active_lock_count == 0


def test_concurrent_todo_ids_and_trace_sequences_are_unique(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "ids.db")
    store.create_session("user", "window")
    with ThreadPoolExecutor(max_workers=8) as pool:
        todos = list(
            pool.map(
                lambda index: store.add_todo("user", "window", "todo {}".format(index)),
                range(32),
            )
        )
    assert sorted(item.id for item in todos) == list(range(1, 33))

    recorder = SQLiteTraceRecorder(store)
    run = recorder.start_run("user", "window", "trace")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda index: store.append_trace_event(run.run_id, "custom", {"n": index}),
                range(24),
            )
        )
    sequences = [item["sequence"] for item in store.list_trace_events(run.run_id)]
    assert sequences == list(range(1, 26))

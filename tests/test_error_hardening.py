"""Sensitive-error redaction and safe HTTP failure tests."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.llm import LLMConfig, LLMRequestError, OpenAICompatibleLLMClient
from app.main import create_app
from app.observability import SQLiteTraceRecorder
from app.security import sanitize_error_message
from tests.api_helpers import make_test_services


@pytest.mark.parametrize(
    "message,secret",
    [
        ("LLM_API_KEY=super-private", "super-private"),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("Bearer token-without-field", "token-without-field"),
        ("password='hunter2'", "hunter2"),
        ("secret: value123", "value123"),
    ],
)
def test_sanitize_error_message_redacts_common_secrets(message: str, secret: str) -> None:
    result = sanitize_error_message(message)
    assert secret not in result
    assert "REDACTED" in result


def test_sanitize_error_message_bounds_copy_without_mutating_exception() -> None:
    error = RuntimeError("secret=keep-original " + "x" * 2000)
    original = str(error)
    result = sanitize_error_message(str(error), max_chars=80)
    assert len(result) <= 80
    assert "keep-original" not in result
    assert str(error) == original


def test_unexpected_api_error_has_no_traceback_or_exception_text(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [])
    app = create_app(services)

    @app.get("/api/test-unexpected")
    def unexpected():
        raise RuntimeError("system Prompt and LLM_API_KEY=do-not-leak")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/test-unexpected")
    serialized = json.dumps(response.json(), ensure_ascii=False)
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "do-not-leak" not in serialized
    assert "traceback" not in serialized.lower()
    assert "system Prompt" not in serialized


def test_failed_trace_uses_the_same_error_redaction(tmp_path: Path) -> None:
    services, _ = make_test_services(tmp_path, [])
    services.store.create_session("user", "window")
    recorder = SQLiteTraceRecorder(services.store)
    run = recorder.start_run("user", "window", "question")
    error = RuntimeError("Authorization: Bearer trace-secret password=pw")
    recorder.fail_run(run.run_id, error)
    trace = recorder.get_trace(run.run_id)
    serialized = json.dumps(trace.to_dict(), ensure_ascii=False)
    assert "trace-secret" not in serialized
    assert "password=pw" not in serialized
    assert str(error).endswith("password=pw")


@pytest.mark.parametrize(
    "status,body",
    [(401, '{"api_key":"private","detail":"denied"}'), (500, "<html>private backend body</html>")],
)
def test_llm_http_error_does_not_expose_response_body(status: int, body: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, request=request)

    config = LLMConfig("fake-key", "https://llm.invalid/v1", "fake-model")
    client = OpenAICompatibleLLMClient(
        config,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMRequestError) as caught:
        client.complete([{"role": "user", "content": "hello"}])
    assert str(status) in str(caught.value)
    assert body not in str(caught.value)
    assert "private" not in str(caught.value)


def test_tracked_repository_has_no_obvious_real_api_key() -> None:
    root = Path(__file__).resolve().parents[1]
    names = subprocess.run(
        ["git", "ls-files"], cwd=root, check=True, capture_output=True, text=True
    ).stdout.splitlines()
    findings = []
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"\bsk-[A-Za-z0-9]{32,}\b", text):
            findings.append(name)
    assert findings == []

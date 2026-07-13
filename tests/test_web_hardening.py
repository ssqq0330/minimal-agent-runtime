"""Static regression tests for browser request races and safe rendering."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
API = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
INSPECTOR = (ROOT / "web" / "inspector.js").read_text(encoding="utf-8")
STATE = (ROOT / "web" / "state.js").read_text(encoding="utf-8")
RENDER = (ROOT / "web" / "render.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "styles.css").read_text(encoding="utf-8")


def test_abort_controllers_cover_history_todo_trace_list_and_detail() -> None:
    assert "new AbortController()" in APP
    assert INSPECTOR.count("new AbortController()") >= 3
    assert "messageAbortController?.abort()" in APP
    assert "todoAbortController?.abort()" in INSPECTOR
    assert "traceListAbortController?.abort()" in INSPECTOR
    assert "traceDetailAbortController?.abort()" in INSPECTOR
    assert "signal" in API


def test_chat_and_inspector_responses_have_full_ownership_checks() -> None:
    assert "requestVersion === chatRequestVersion" in APP
    assert "state.userId === requestUserId" in APP
    assert "state.activeSessionId === requestSessionId" in APP
    assert "requestVersion === todoRequestVersion" in INSPECTOR
    assert "requestVersion === traceListRequestVersion" in INSPECTOR
    assert "requestVersion === traceDetailRequestVersion" in INSPECTOR
    assert "detail.run.run_id === runId" in INSPECTOR


def test_send_is_guarded_by_busy_offline_empty_and_length_states() -> None:
    assert "if (state.isSending)" in APP
    assert "state.isSending: true" not in APP
    assert "!state.serviceAvailable" in APP
    assert "MAX_MESSAGE_LENGTH = 8000" in APP
    assert 'maxlength="8000"' in HTML
    assert "messageTooLong" in APP
    assert "dom.sendButton.disabled" in APP


def test_friendly_http_and_invalid_json_messages_exist() -> None:
    for status in (503, 502, 508, 422):
        assert "error.status === {}".format(status) in APP
    assert "invalid_response" in API
    assert "后端返回格式异常" in APP


def test_dynamic_content_and_trace_json_remain_safe() -> None:
    combined = APP + INSPECTOR + RENDER
    assert "eval(" not in combined
    assert "new Function" not in combined
    assert ".innerHTML" not in combined
    assert "createTextNode" in RENDER
    assert "pre.textContent = JSON.stringify" in INSPECTOR


def test_local_storage_contains_only_preferences() -> None:
    assert "localStorage" not in APP
    assert "localStorage" not in INSPECTOR
    for forbidden in ("messages:", "todos:", "traceRuns:"):
        assert forbidden not in "\n".join(
            line for line in STATE.splitlines() if "STORAGE_KEYS" in line
        )
    assert set(
        value for value in (
            "minimal-agent.user-id",
            "minimal-agent.active-session-id",
            "minimal-agent.sidebar-collapsed",
            "minimal-agent.inspector-open",
            "minimal-agent.inspector-tab",
        ) if value in STATE
    )


def test_escape_reduced_motion_and_no_external_cdn() -> None:
    assert 'event.key === "Escape"' in INSPECTOR
    assert "prefers-reduced-motion" in CSS
    assert "https://" not in HTML
    assert "http://" not in HTML

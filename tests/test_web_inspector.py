"""Static contract checks for the Todo and Trace Inspector UI."""

from pathlib import Path
import re


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
CSS = (WEB_DIR / "styles.css").read_text(encoding="utf-8")
API_JS = (WEB_DIR / "api.js").read_text(encoding="utf-8")
STATE_JS = (WEB_DIR / "state.js").read_text(encoding="utf-8")
APP_JS = (WEB_DIR / "app.js").read_text(encoding="utf-8")
INSPECTOR_JS = (WEB_DIR / "inspector.js").read_text(encoding="utf-8")
RENDER_JS = (WEB_DIR / "render.js").read_text(encoding="utf-8")
ALL_JS = "\n".join((API_JS, STATE_JS, APP_JS, INSPECTOR_JS, RENDER_JS))


def test_inspector_has_required_semantic_structure() -> None:
    required_ids = {
        "inspector-panel",
        "toggle-inspector-button",
        "inspector-tabs",
        "overview-tab-button",
        "todo-tab-button",
        "trace-tab-button",
        "overview-panel",
        "todo-panel",
        "trace-panel",
        "todo-list",
        "todo-empty-state",
        "refresh-todos-button",
        "todo-loading",
        "trace-run-list",
        "trace-empty-state",
        "refresh-traces-button",
        "trace-loading",
        "trace-detail",
        "trace-event-list",
        "delete-trace-button",
    }
    for element_id in required_ids:
        assert 'id="{}"'.format(element_id) in HTML


def test_tabs_and_panels_are_accessible() -> None:
    for element_id in (
        "overview-tab-button",
        "todo-tab-button",
        "trace-tab-button",
    ):
        tag = re.search(
            r'<button\b[^>]*id="{}"[^>]*>'.format(element_id), HTML, re.DOTALL
        )
        assert tag is not None
        assert 'role="tab"' in tag.group(0)
        assert 'aria-selected="' in tag.group(0)

    assert len(re.findall(r'role="tabpanel"', HTML)) >= 3


def test_overview_contains_all_metrics() -> None:
    for element_id in (
        "current-run-id",
        "metric-llm-calls",
        "metric-tool-calls",
        "metric-context-compressed",
        "metric-loaded-history",
        "metric-run-status",
        "metric-run-duration",
    ):
        assert 'id="{}"'.format(element_id) in HTML


def test_api_exports_todo_and_trace_requests() -> None:
    assert "export function listTodos" in API_JS
    assert "export function listTraceRuns" in API_JS
    assert "export function getTrace" in API_JS
    assert "export function deleteTrace" in API_JS
    assert 'method: "DELETE"' in API_JS
    assert "/todos" in API_JS
    assert "/api/traces" in API_JS


def test_api_encodes_paths_and_query_parameters() -> None:
    assert "URLSearchParams" in API_JS
    assert "encodeURIComponent(sessionId)" in API_JS
    assert "encodeURIComponent(runId)" in API_JS


def test_inspector_state_and_preferences_are_declared() -> None:
    for field in (
        "inspectorOpen",
        "activeInspectorTab",
        "todos",
        "traceRuns",
        "selectedRunId",
        "traceDetail",
        "isLoadingTodos",
        "isLoadingTraceRuns",
        "isLoadingTraceDetail",
        "isDeletingTrace",
    ):
        assert field in STATE_JS
    assert "minimal-agent.inspector-open" in STATE_JS
    assert "minimal-agent.inspector-tab" in STATE_JS


def test_browser_storage_contains_preferences_only() -> None:
    keys = set(re.findall(r'"(minimal-agent\.[^"]+)"', STATE_JS))
    assert keys == {
        "minimal-agent.user-id",
        "minimal-agent.active-session-id",
        "minimal-agent.sidebar-collapsed",
        "minimal-agent.inspector-open",
        "minimal-agent.inspector-tab",
    }
    assert re.search(r"localStorage\.setItem\([^\n]*(todo|trace|message|run)", STATE_JS, re.I) is None


def test_chat_success_refreshes_inspector_without_blocking_message_render() -> None:
    render_index = APP_JS.index("renderMessages();", APP_JS.index("async function submitMessage"))
    refresh_index = APP_JS.index("refreshInspectorAfterChat(result)")
    assert render_index < refresh_index
    assert "void refreshInspectorAfterChat(result)" in APP_JS
    assert "refreshTodos({ quiet: false })" in INSPECTOR_JS
    assert "refreshTraceRuns({ preferredRunId: result.run_id" in INSPECTOR_JS
    assert "lastRunId: result.run_id" in INSPECTOR_JS


def test_session_and_user_changes_clear_inspector_state() -> None:
    assert STATE_JS.count("clearInspectorState();") >= 2
    assert "todos: []" in STATE_JS
    assert "traceRuns: []" in STATE_JS
    assert "selectedRunId: null" in STATE_JS
    assert "traceDetail: null" in STATE_JS


def test_todo_and_trace_responses_check_ownership() -> None:
    assert "state.userId === requestUserId" in INSPECTOR_JS
    assert "state.activeSessionId === requestSessionId" in INSPECTOR_JS
    assert "detail.run.user_id === requestUserId" in INSPECTOR_JS
    assert "detail.run.session_id === requestSessionId" in INSPECTOR_JS
    assert "state.selectedRunId === runId" in INSPECTOR_JS


def test_safe_message_renderer_supports_requested_subset() -> None:
    assert "export function renderSafeMessage" in RENDER_JS
    assert 'token.startsWith("**")' in RENDER_JS
    assert 'document.createElement("code")' not in RENDER_JS or "code" in RENDER_JS
    assert 'line.startsWith("- ")' in RENDER_JS
    assert "document.createTextNode" in RENDER_JS
    assert "renderSafeMessage(bubble, message.content)" in APP_JS


def test_dynamic_content_avoids_unsafe_html_and_code_execution() -> None:
    assert "innerHTML" not in ALL_JS
    assert re.search(r"\beval\s*\(", ALL_JS) is None
    assert "new Function" not in ALL_JS
    assert "pre.textContent = JSON.stringify(value, null, 2)" in INSPECTOR_JS
    assert "textContent" in INSPECTOR_JS


def test_page_has_no_external_assets_or_api_keys() -> None:
    assert "https://" not in HTML
    assert "http://" not in HTML
    assert re.search(r"sk-[A-Za-z0-9_-]{12,}", HTML + ALL_JS) is None
    assert "Authorization" not in HTML + ALL_JS


def test_inspector_css_has_desktop_medium_and_mobile_layouts() -> None:
    assert ".inspector-panel" in CSS
    assert "grid-area: inspector" in CSS
    assert "@media (max-width: 1280px)" in CSS
    assert "@media (max-width: 760px)" in CSS
    assert ".inspector-collapsed .inspector-panel" in CSS


def test_css_preserves_accessibility_and_overflow_safety() -> None:
    assert "#apply-user-button" in CSS
    assert "white-space: nowrap" in CSS
    assert ".trace-event-content pre" in CSS
    assert "overflow: auto" in CSS
    assert ":focus-visible" in CSS
    assert "prefers-reduced-motion" in CSS
    assert "min-width: 0" in CSS


def test_existing_util_is_used_for_inspector_dates() -> None:
    assert "formatDateTime" in INSPECTOR_JS
    assert 'from "/static/utils.js"' in INSPECTOR_JS

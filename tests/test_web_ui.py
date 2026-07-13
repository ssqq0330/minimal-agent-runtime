"""Static and FastAPI delivery checks for the native Web UI."""

from pathlib import Path
import re

from fastapi.testclient import TestClient

from app.main import app


WEB_DIR = Path(__file__).resolve().parent.parent / "web"
HTML = (WEB_DIR / "index.html").read_text(encoding="utf-8")
JAVASCRIPT = "\n".join(
    path.read_text(encoding="utf-8")
    for path in (WEB_DIR / "app.js", WEB_DIR / "api.js", WEB_DIR / "state.js")
)


def test_home_returns_html() -> None:
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_home_contains_required_semantic_ids() -> None:
    required_ids = {
        "app-title",
        "user-id-input",
        "apply-user-button",
        "service-status",
        "session-sidebar",
        "session-list",
        "new-session-button",
        "refresh-sessions-button",
        "toggle-sidebar-button",
        "current-session-title",
        "rename-session-button",
        "delete-session-button",
        "message-list",
        "empty-chat-state",
        "chat-loading",
        "message-input",
        "send-button",
        "character-count",
        "toast-container",
    }

    for element_id in required_ids:
        assert 'id="{}"'.format(element_id) in HTML


def test_home_uses_es_module_and_accessible_composer() -> None:
    assert '<script type="module" src="/static/app.js"></script>' in HTML
    assert '<label for="message-input">' in HTML or 'aria-label=' in re.search(
        r'<textarea[^>]*id="message-input"[^>]*>', HTML, re.DOTALL
    ).group(0)
    assert "<main" in HTML
    assert "<aside" in HTML
    assert "<header" in HTML


def test_buttons_have_text_or_accessible_names() -> None:
    buttons = re.findall(r"<button\b[^>]*>.*?</button>", HTML, re.DOTALL)
    assert buttons
    for button in buttons:
        opening_tag = button.split(">", 1)[0]
        visible_text = re.sub(r"<[^>]+>", "", button.split(">", 1)[1]).strip()
        assert visible_text or "aria-label=" in opening_tag


def test_static_assets_are_served() -> None:
    client = TestClient(app)
    for path, content_type in (
        ("/static/app.js", "text/javascript"),
        ("/static/api.js", "text/javascript"),
        ("/static/state.js", "text/javascript"),
        ("/static/utils.js", "text/javascript"),
        ("/static/styles.css", "text/css"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)


def test_javascript_references_required_api_routes() -> None:
    assert "/api/health" in JAVASCRIPT
    assert "/api/sessions" in JAVASCRIPT
    assert "/api/chat" in JAVASCRIPT


def test_page_has_no_external_assets_inline_handlers_or_secrets() -> None:
    assert "https://" not in HTML
    assert "http://" not in HTML
    assert re.search(r"\son[a-z]+\s*=", HTML, re.IGNORECASE) is None
    combined = HTML + JAVASCRIPT
    assert re.search(r"sk-[A-Za-z0-9_-]{12,}", combined) is None
    assert "Authorization" not in combined


def test_javascript_avoids_dynamic_code_execution() -> None:
    assert re.search(r"\beval\s*\(", JAVASCRIPT) is None
    assert "new Function" not in JAVASCRIPT


def test_local_storage_is_namespaced_and_preferences_only() -> None:
    state_source = (WEB_DIR / "state.js").read_text(encoding="utf-8")
    keys = re.findall(r'"(minimal-agent\.[^"]+)"', state_source)

    assert set(keys) == {
        "minimal-agent.user-id",
        "minimal-agent.active-session-id",
        "minimal-agent.sidebar-collapsed",
    }
    assert "localStorage.setItem" in state_source
    assert re.search(r"localStorage\.setItem\([^\n]*(message|trace|todo)", state_source, re.I) is None


def test_existing_health_endpoint_remains_available() -> None:
    response = TestClient(app).get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"

"""Tests for FastAPI service injection, degraded startup, and shutdown."""

from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main_module
from app.dependencies import create_degraded_services
from app.llm import LLMConfigurationError
from app.main import create_app
from tests.api_helpers import make_test_services


def test_create_app_health_and_static_home_with_injected_services(
    tmp_path: Path,
) -> None:
    services, _ = make_test_services(tmp_path)
    app = create_app(services)
    client = TestClient(app)

    health = client.get("/api/health")
    home = client.get("/")
    css = client.get("/static/styles.css")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "minimal-agent-runtime",
        "llm_configured": True,
        "database": "available",
    }
    assert home.status_code == 200
    assert "Minimal Agent Runtime" in home.text
    assert css.status_code == 200


def test_lifespan_closes_internally_owned_client(tmp_path: Path) -> None:
    services, llm = make_test_services(tmp_path, owns_client=True)
    app = create_app(services)

    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert llm.closed is False

    assert llm.closed is True


def test_lifespan_does_not_close_externally_owned_client(tmp_path: Path) -> None:
    services, llm = make_test_services(tmp_path, owns_client=False)
    app = create_app(services)

    with TestClient(app) as client:
        assert client.get("/api/health").json()["llm_configured"] is True

    assert llm.closed is False


def test_missing_llm_config_uses_degraded_services_and_keeps_health_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "degraded" / "agent.db"

    def missing_config(path):  # type: ignore[no-untyped-def]
        raise LLMConfigurationError("missing")

    monkeypatch.setattr(main_module, "create_application_services", missing_config)
    app = create_app(db_path=db_path)

    with TestClient(app) as client:
        health = client.get("/api/health")
        home = client.get("/")
        created = client.post(
            "/api/sessions",
            json={"user_id": "user", "session_id": "window"},
        )
        chat = client.post(
            "/api/chat",
            json={"user_id": "user", "session_id": "window", "message": "hi"},
        )

    assert health.status_code == 200
    assert health.json()["llm_configured"] is False
    assert health.json()["database"] == "available"
    assert home.status_code == 200
    assert created.status_code == 201
    assert chat.status_code == 503


def test_degraded_services_close_is_safe(tmp_path: Path) -> None:
    services = create_degraded_services(tmp_path / "safe.db")
    services.close()
    assert services.llm_configured is False

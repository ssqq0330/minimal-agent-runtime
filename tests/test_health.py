"""Tests for the service health endpoint."""

from fastapi.testclient import TestClient

from app.main import app


def test_health_check() -> None:
    """The health endpoint returns the expected service metadata."""
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "minimal-agent-runtime"
    assert response.json()["llm_configured"] is False
    assert response.json()["database"] == "unavailable"

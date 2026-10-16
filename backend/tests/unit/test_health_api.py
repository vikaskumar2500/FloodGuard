import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.health import DependencyHealth


@pytest.mark.parametrize("path", ["/health", "/health/live", "/api/v1/health/live"])
def test_liveness_metadata(client, path):
    response = client.get(path, headers={"X-Request-ID": "test-live-1"})
    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "floodguard-api",
        "version": "0.1.0",
        "request_id": "test-live-1",
    }
    assert response.headers["x-request-id"] == "test-live-1"


@pytest.mark.parametrize("path", ["/api/v1/health", "/api/v1/health/ready"])
def test_readiness_healthy(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert set(response.json()["dependencies"]) == {"postgres", "postgis", "redis"}
    assert response.headers["cache-control"] == "no-store"


def test_database_failure_fails_readiness_but_not_liveness(client, monkeypatch):
    async def failed(*args):
        return {
            "postgres": DependencyHealth(status="unavailable", message="Database unavailable"),
            "postgis": DependencyHealth(status="unavailable", message="PostGIS not verified"),
        }

    monkeypatch.setattr("app.services.health.check_database", failed)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["ready"] is False
    assert client.get("/api/v1/health/live").status_code == 200


def test_missing_postgis_fails_readiness(client, monkeypatch):
    async def failed(*args):
        return {
            "postgres": DependencyHealth(status="healthy", message="Database reachable"),
            "postgis": DependencyHealth(status="unavailable", message="PostGIS unavailable"),
        }

    monkeypatch.setattr("app.services.health.check_database", failed)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_redis_failure_reports_degraded_and_not_ready(client, monkeypatch):
    async def failed(*args):
        return DependencyHealth(status="unavailable", message="Redis unavailable")

    monkeypatch.setattr("app.services.health.check_redis", failed)
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
    assert response.json()["ready"] is False


def test_optional_redis_reports_degraded_but_ready(client, monkeypatch):
    async def failed(*args):
        return DependencyHealth(status="unavailable", message="Redis unavailable")

    monkeypatch.setattr("app.services.health.check_redis", failed)
    client.app.state.settings.redis_required = False
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["status"] == "degraded"


def test_errors_are_safe_and_have_request_ids(client):
    response = client.get("/missing", headers={"X-Request-ID": "invalid id contains spaces"})
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["request_id"] == response.headers["x-request-id"]
    assert response.json()["request_id"] != "invalid id contains spaces"


def test_unhandled_error_never_exposes_secrets(client):
    @client.app.get("/test-error")
    async def crash():
        raise RuntimeError("postgresql://private-host:password-secret")

    response = client.get("/test-error")
    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "password-secret" not in response.text
    assert "private-host" not in response.text


def test_cors_accepts_configured_origin_and_rejects_other_origins(client):
    headers = {"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    allowed = client.options("/api/v1/health/ready", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = client.options(
        "/api/v1/health/ready", headers={**headers, "Origin": "https://untrusted.example"}
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_custom_api_prefix(client, settings):
    settings.api_v1_prefix = "/api/custom"
    with TestClient(create_app(settings)) as custom:
        assert custom.get("/api/custom/health/live").status_code == 200
        assert custom.get("/api/v1/health/live").status_code == 404
        assert custom.get("/api/custom/openapi.json").status_code == 200
        assert custom.get("/docs").status_code == 200

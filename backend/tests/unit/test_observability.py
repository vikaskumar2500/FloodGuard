import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def obs_client():
    app = create_app(get_settings())
    with TestClient(app) as client:
        yield client


def test_live_health_observability(obs_client):
    response = obs_client.get("/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_health_observability(obs_client):
    response = obs_client.get("/ready")
    assert response.status_code == 200
    assert response.json()["db"] == "connected"


def test_internal_health_observability(obs_client):
    response = obs_client.get("/api/v1/internal/health")
    assert response.status_code == 200
    data = response.json()
    assert data["core"]["database"] == "ok"
    assert data["degradable"]["ml"] == "ok"


def test_correlation_id_middleware(obs_client):
    response = obs_client.get("/live")
    assert "x-correlation-id" in response.headers

    # Test setting custom
    response2 = obs_client.get("/live", headers={"x-correlation-id": "custom-123"})
    assert response2.headers["x-correlation-id"] == "custom-123"

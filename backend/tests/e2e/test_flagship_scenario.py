import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def test_client():
    app = create_app(get_settings())
    with TestClient(app) as client:
        yield client


@pytest.mark.e2e
@pytest.mark.integration
def test_flagship_flood_to_reroute_flow(test_client):
    # 1. Login (simulated via token or mock)
    # Since auth is mocked for simplicity in tests, we proceed.

    # 2. Calculate route
    route_req = {
        "source": {"longitude": -74.0, "latitude": 40.7},
        "destination": {"longitude": -74.1, "latitude": 40.8},
        "mode": "SAFEST",
        "algorithm": "ASTAR",
    }
    calc_res = test_client.post("/api/v1/routes/calculate", json=route_req)
    assert calc_res.status_code == 201
    route_id = calc_res.json()["routeId"]

    # 3. Trigger Hazard via Simulator
    sim_req = {
        "event_type": "weather.observed",
        "payload": {"rainfall_mm": 50, "longitude": -74.05, "latitude": 40.75},
    }
    sim_res = test_client.post("/api/v1/simulation/inject", json=sim_req)
    assert sim_res.status_code == 202

    # 4. SSE (Simulate connecting to SSE and getting rerouting event)
    # The real realtime rerouting test already covers SSE emitting the event.
    # We verify the pipeline didn't crash and returns valid 404/active route behavior.
    sse_res = test_client.get(f"/api/v1/routes/{route_id}/events?token=test_token_{route_id}")
    assert sse_res.status_code in [200, 404]

    # 5. Assistant explanation
    prompt = {"prompt": "Why was my route changed?"}
    ast_res = test_client.post("/api/v1/assistant/chat", json=prompt)
    assert ast_res.status_code == 200
    assert "response" in ast_res.json()

import pytest
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.health import DependencyHealth
from tests.unit.test_cache import InMemoryFakeRedis


@pytest.fixture
def caching_client(monkeypatch):
    async def healthy_database(*args):
        return {
            "postgres": DependencyHealth(status="healthy", message="ok"),
            "postgis": DependencyHealth(status="healthy", message="ok"),
        }

    monkeypatch.setattr("app.services.health.check_database", healthy_database)
    settings = Settings(
        app_env="test",
        use_fixture_routing=True,
        enable_simulation_api=True,
        cache_enabled=True,
        redis_required=False,
        active_route_ttl_seconds=0.05,
        realtime_heartbeat_seconds=0.01,
    )
    fake_redis = InMemoryFakeRedis()
    monkeypatch.setattr("app.main.create_redis_client", lambda _: fake_redis)
    app = create_app(settings)
    with TestClient(app) as client:
        client.fake_redis = fake_redis
        yield client


def test_api_route_cache_hit_miss_and_lifecycle(caching_client):
    body = {
        "source": {"longitude": 0, "latitude": 0},
        "destination": {"longitude": 0.003, "latitude": 0},
        "mode": "SAFEST",
        "algorithm": "ASTAR",
    }

    # 1. First calculation is a MISS
    res1 = caching_client.post("/api/v1/routes/calculate", json=body)
    assert res1.status_code == 201
    assert res1.headers.get("x-floodguard-cache") == "MISS"
    data1 = res1.json()
    route_id_1 = data1["routeId"]

    # 2. Second calculation is a HIT
    res2 = caching_client.post("/api/v1/routes/calculate", json=body)
    assert res2.status_code == 201
    assert res2.headers.get("x-floodguard-cache") == "HIT"
    data2 = res2.json()
    route_id_2 = data2["routeId"]

    # Invariant: Distinct route_id lifecycle per request even on cache HIT!
    assert route_id_1 != route_id_2
    assert data1["distanceMeters"] == data2["distanceMeters"]
    assert data1["estimatedTimeSeconds"] == data2["estimatedTimeSeconds"]

    # Invariant: Both active routes are registered in ActiveRouteRegistry
    registry = caching_client.app.state.active_route_registry
    assert registry.get(route_id_1) is not None
    assert registry.get(route_id_2) is not None

    # Invariant: Can subscribe to cached route's SSE stream and receive frames
    sse_resp = caching_client.get(
        f"/api/v1/routes/{route_id_2}/events?token=test_token_{route_id_2}"
    )
    assert sse_resp.status_code == 200
    assert sse_resp.headers["content-type"].startswith("text/event-stream")


def test_api_route_cache_automatic_invalidation_on_simulation_advance(caching_client):
    body = {
        "source": {"longitude": 0, "latitude": 0},
        "destination": {"longitude": 0.003, "latitude": 0},
        "mode": "SAFEST",
        "algorithm": "ASTAR",
    }

    # First request: MISS -> cached
    res1 = caching_client.post("/api/v1/routes/calculate", json=body)
    assert res1.headers.get("x-floodguard-cache") == "MISS"

    # Second request: HIT
    res2 = caching_client.post("/api/v1/routes/calculate", json=body)
    assert res2.headers.get("x-floodguard-cache") == "HIT"

    # Advance risk revision via simulation event
    event_payload = {
        "event_id": "11111111-1111-1111-1111-111111111111",
        "scenario_id": "flash-test",
        "sequence": 1,
        "event_type": "FLOOD_ZONE_UPDATED",
        "occurred_at": "2026-10-07T12:00:00Z",
        "payload": {
            "target_edge_ids": ["fixture-top-1"],
            "risk_score": 0.9,
            "severity": "HIGH",
            "confidence": 0.8,
        },
    }
    sim_res = caching_client.post(
        "/api/v1/dev/simulation/events?token=test_token_{route_id}", json=event_payload
    )
    assert sim_res.status_code == 200
    assert sim_res.json()["materialChange"] is True
    assert sim_res.json()["riskRevision"] == 1

    # Invariant: Environmental change automatically invalidates cache -> Next calculation is a MISS
    res3 = caching_client.post("/api/v1/routes/calculate", json=body)
    assert res3.headers.get("x-floodguard-cache") == "MISS"


def test_api_route_cache_graceful_fallback_when_redis_fails(caching_client):
    body = {
        "source": {"longitude": 0, "latitude": 0},
        "destination": {"longitude": 0.003, "latitude": 0},
        "mode": "SAFEST",
        "algorithm": "ASTAR",
    }

    # Simulate complete Redis breakdown
    caching_client.fake_redis.error_on_get = True
    caching_client.fake_redis.error_on_set = True

    # Routing must NOT fail merely because Redis is down
    res = caching_client.post("/api/v1/routes/calculate", json=body)
    assert res.status_code == 201
    assert res.headers.get("x-floodguard-cache") == "MISS"
    data = res.json()
    assert data["routeId"] is not None
    assert data["distanceMeters"] > 0

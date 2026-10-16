from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.realtime.registry import ActiveRoute, ActiveRouteRegistry
from app.schemas.health import DependencyHealth


def runtime_client(monkeypatch, **overrides):
    async def healthy_database(*args):
        return {
            "postgres": DependencyHealth(status="healthy", message="ok"),
            "postgis": DependencyHealth(status="healthy", message="ok"),
        }

    async def healthy_redis(*args):
        return DependencyHealth(status="healthy", message="ok")

    monkeypatch.setattr("app.services.health.check_database", healthy_database)
    monkeypatch.setattr("app.services.health.check_redis", healthy_redis)
    settings = Settings(
        _env_file=None,
        app_env="test",
        enable_simulation_api=True,
        use_fixture_routing=True,
        **overrides,
    )
    return TestClient(create_app(settings))


def event(event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid4()),
        "scenario_id": "flash-test",
        "sequence": 1,
        "event_type": "FLOOD_ZONE_UPDATED",
        "occurred_at": datetime.now(UTC).isoformat(),
        "payload": {
            "zone_id": "top",
            "severity": "SEVERE",
            "risk_score": 0.95,
            "confidence": 0.9,
            "target_edge_ids": ["fixture-top-1", "fixture-top-2", "fixture-top-3"],
        },
    }


def test_running_http_simulation_pipeline_reroutes_once_and_deduplicates(monkeypatch) -> None:
    with runtime_client(monkeypatch) as client:
        response = client.post(
            "/api/v1/routes/calculate",
            json={
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            },
        )
        assert response.status_code == 201
        route_id = response.json()["routeId"]
        queue = client.app.state.runtime.realtime_publisher.subscribe(route_id)
        payload = event()
        applied = client.post(
            "/api/v1/dev/simulation/events?token=test_token_{route_id}", json=payload
        )
        duplicate = client.post(
            "/api/v1/dev/simulation/events?token=test_token_{route_id}", json=payload
        )
        assert applied.status_code == 200
        assert applied.json()["materialChange"] is True
        assert duplicate.json()["duplicate"] is True
        events = [queue.get_nowait() for _ in range(3)]
        assert [item.eventType for item in events] == [
            "route.invalidated",
            "route.rerouting",
            "route.recalculated",
        ]
        assert [item.sequence for item in events] == [1, 2, 3]
        assert events[-1].data.geometry["type"] == "LineString"
        assert client.app.state.runtime.reroute_coordinator.reroute_count == 1
        assert client.app.state.runtime.route_registry.get(route_id) is None
        assert client.app.state.runtime.route_registry.get(events[-1].data.newRouteId) is not None


def test_simulation_endpoint_is_hidden_in_production(monkeypatch) -> None:
    async def healthy_database(*args):
        return {}

    async def healthy_redis(*args):
        return DependencyHealth(status="healthy", message="ok")

    monkeypatch.setattr("app.services.health.check_database", healthy_database)
    monkeypatch.setattr("app.services.health.check_redis", healthy_redis)
    settings = Settings(_env_file=None, app_env="production", redis_required=False)
    with TestClient(create_app(settings)) as client:
        assert (
            client.post(
                "/api/v1/dev/simulation/events?token=test_token_{route_id}", json=event()
            ).status_code
            == 404
        )


def test_registry_expiration_removes_route_and_edge_index() -> None:
    now = datetime(2026, 10, 7, tzinfo=UTC)

    def clock():
        return now

    registry = ActiveRouteRegistry(clock=clock, ttl_seconds=30)
    route = ActiveRoute(
        str(uuid4()),
        "graph",
        "SAFEST",
        (0, 0),
        (1, 1),
        ["edge"],
        0.1,
        "LOW",
        100,
        created_at=now,
        expires_at=now - timedelta(seconds=1),
    )
    registry.register(route)
    assert registry.get(route.route_id) is None
    assert registry.routes_using_edges({"edge"}) == set()


def test_real_sse_transport_frames_heartbeat_and_closes_on_expiration(monkeypatch) -> None:
    with runtime_client(
        monkeypatch, active_route_ttl_seconds=0.05, realtime_heartbeat_seconds=0.01
    ) as client:
        calculated = client.post(
            "/api/v1/routes/calculate",
            json={
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            },
        )
        route_id = calculated.json()["routeId"]

        response = client.get(f"/api/v1/routes/{route_id}/events?token=test_token_{route_id}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        assert "event: heartbeat\n" in response.text
        assert "id: 1\n" in response.text
        assert response.text.endswith("\n\n")
        assert client.app.state.runtime.route_registry.get(route_id) is None
        assert route_id not in client.app.state.runtime.realtime_publisher._subscribers


def test_subscription_to_expired_route_returns_404(monkeypatch) -> None:
    with runtime_client(monkeypatch, active_route_ttl_seconds=0.01) as client:
        calculated = client.post(
            "/api/v1/routes/calculate",
            json={
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            },
        )
        route_id = calculated.json()["routeId"]
        # Fast-forward / expire the route
        route = client.app.state.runtime.route_registry._routes[route_id]
        client.app.state.runtime.route_registry._routes[route_id] = ActiveRoute(
            route_id=route.route_id,
            graph_version_id=route.graph_version_id,
            mode=route.mode,
            source=route.source,
            destination=route.destination,
            edge_ids=route.edge_ids,
            risk_score=route.risk_score,
            risk_level=route.risk_level,
            current_eta_s=route.current_eta_s,
            created_at=route.created_at,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )

        response = client.get(f"/api/v1/routes/{route_id}/events?token=test_token_{route_id}")
        assert response.status_code == 404
        assert client.app.state.runtime.route_registry.get(route_id) is None


def test_expired_route_ignored_by_risk_update_and_does_not_reroute(monkeypatch) -> None:
    with runtime_client(monkeypatch) as client:
        calculated = client.post(
            "/api/v1/routes/calculate",
            json={
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            },
        )
        route_id = calculated.json()["routeId"]
        # Expire route
        route = client.app.state.runtime.route_registry._routes[route_id]
        client.app.state.runtime.route_registry._routes[route_id] = ActiveRoute(
            route_id=route.route_id,
            graph_version_id=route.graph_version_id,
            mode=route.mode,
            source=route.source,
            destination=route.destination,
            edge_ids=route.edge_ids,
            risk_score=route.risk_score,
            risk_level=route.risk_level,
            current_eta_s=route.current_eta_s,
            created_at=route.created_at,
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        # Apply flood update
        applied = client.post(
            "/api/v1/dev/simulation/events?token=test_token_{route_id}", json=event()
        )
        assert applied.status_code == 200
        assert client.app.state.runtime.reroute_coordinator.reroute_count == 0


def test_backend_sink_emits_simulation_events_to_running_server(monkeypatch) -> None:
    from simulations.models import EventType as SimEventType
    from simulations.models import SimulationEvent as SimEvent
    from simulations.sinks.backend import BackendSink

    with runtime_client(monkeypatch) as client:
        calculated = client.post(
            "/api/v1/routes/calculate",
            json={
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            },
        )
        route_id = calculated.json()["routeId"]
        queue = client.app.state.runtime.realtime_publisher.subscribe(route_id)

        # Use BackendSink with sender delegating to client.post
        def client_sender(evt: SimEvent) -> None:
            resp = client.post(
                "/api/v1/dev/simulation/events?token=test_token_{route_id}", json=evt.to_dict()
            )
            if resp.status_code >= 400:
                raise RuntimeError(f"error: {resp.status_code}")

        sink = BackendSink(
            "http://testserver/api/v1/dev/simulation/events?token=test_token_{route_id}",
            sender=client_sender,
        )
        sim_evt = SimEvent.create(
            "test-sink-1",
            1,
            SimEventType.FLOOD_ZONE_UPDATED,
            datetime.now(UTC),
            {
                "zone_id": "top",
                "severity": "SEVERE",
                "risk_score": 0.95,
                "confidence": 0.9,
                "target_edge_ids": ["fixture-top-1", "fixture-top-2", "fixture-top-3"],
            },
        )
        sink.emit(sim_evt)
        assert sink.events_emitted == 1

        events = [queue.get_nowait() for _ in range(3)]
        assert [e.eventType for e in events] == [
            "route.invalidated",
            "route.rerouting",
            "route.recalculated",
        ]


def test_runtime_shutdown_cleans_resources_without_pending_tasks(monkeypatch) -> None:
    with runtime_client(monkeypatch) as client:
        calculated = client.post(
            "/api/v1/routes/calculate",
            json={
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            },
        )
        route_id = calculated.json()["routeId"]
        client.app.state.runtime.realtime_publisher.subscribe(route_id)
        # Ensure active route and subscriber exist before shutdown
        assert client.app.state.runtime.route_registry.get(route_id) is not None
        assert route_id in client.app.state.runtime.realtime_publisher._subscribers
    # Outside context manager: shutdown has executed
    assert len(client.app.state.runtime.realtime_publisher._subscribers) == 0
    assert len(client.app.state.runtime.route_registry._routes) == 0

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.realtime.coordinator import (
    RealtimeRerouteCoordinator,
    ReplacementRoute,
    RouteEvaluation,
    RuntimeRiskState,
)
from app.realtime.event_bus import InMemoryEventBus
from app.realtime.events import RouteRiskUpdatedData
from app.realtime.publisher import RealtimePublisher
from app.realtime.registry import ActiveRoute, ActiveRouteRegistry
from app.realtime.rerouting import RouteImpactDetector, RouteReroutingService


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


def test_event_bus_publishes_and_subscribers_receive(bus: InMemoryEventBus) -> None:
    received: list[dict] = []

    bus.subscribe("route.risk_updated", lambda event: received.append(event))
    bus.publish({"eventType": "route.risk_updated", "routeId": "r-1"})

    assert len(received) == 1
    assert received[0]["routeId"] == "r-1"


def test_active_route_registry_uses_edge_ids() -> None:
    registry = ActiveRouteRegistry()
    route = ActiveRoute(
        route_id="route-1",
        graph_version_id="g-1",
        mode="SAFEST",
        source=(0.0, 0.0),
        destination=(1.0, 1.0),
        edge_ids=["edge-1", "edge-2"],
        risk_score=0.4,
        risk_level="MODERATE",
        current_eta_s=180,
    )
    registry.register(route)

    assert registry.routes_using_edges({"edge-2"}) == {"route-1"}
    assert registry.get("route-1") is not None
    assert registry.get("route-1").edge_ids == route.edge_ids


def test_impact_detector_marks_routes_for_reroute() -> None:
    registry = ActiveRouteRegistry()
    registry.register(
        ActiveRoute(
            route_id="route-1",
            graph_version_id="g-1",
            mode="SAFEST",
            source=(0.0, 0.0),
            destination=(1.0, 1.0),
            edge_ids=["edge-1", "edge-2"],
            risk_score=0.2,
            risk_level="LOW",
            current_eta_s=180,
        )
    )
    detector = RouteImpactDetector(registry)

    affected = detector.detect_affected_routes({"edge-2"}, threshold=0.3)

    assert affected == {"route-1"}


def test_rerouting_service_uses_new_route_when_risk_crosses_threshold() -> None:
    service = RouteReroutingService(
        risk_change_threshold=0.3,
        reroute_improvement_threshold=0.1,
        cooldown_seconds=0,
    )
    decision = service.decide(
        current_risk=0.68,
        current_eta_s=180,
        candidate_risk=0.2,
        candidate_eta_s=210,
        affected_edge_ids={"edge-2"},
        current_level="HIGH",
        candidate_level="LOW",
        route_is_affected=True,
    )

    assert decision["should_reroute"] is True
    assert decision["reason"] == "route_unsafe"


def test_runtime_risk_revision_is_material_and_deduplicated() -> None:
    state = RuntimeRiskState(threshold=0.3)
    assert state.apply("one", {"edge": (0.1, "LOW", False)}) == (1, {"edge"})
    assert state.apply("two", {"edge": (0.2, "LOW", False)}) == (1, set())
    assert state.apply("three", {"edge": (0.2, "MODERATE", False)}) == (2, {"edge"})
    assert state.apply("three", {"edge": (0.9, "SEVERE", True)}) == (2, set())


def test_hysteresis_and_cooldown_prevent_flapping() -> None:
    now = datetime(2026, 10, 7, tzinfo=UTC)
    service = RouteReroutingService(clock=lambda: now, cooldown_seconds=30)
    decision = service.decide(
        mode="SAFEST",
        current_risk=0.68,
        current_eta_s=210,
        candidate_risk=0.2,
        candidate_eta_s=180,
        affected_edge_ids={"edge"},
        route_is_affected=True,
        current_level="MODERATE",
        candidate_level="LOW",
        unsafe_latched=True,
        last_rerouted_at=now - timedelta(seconds=10),
    )
    assert decision.should_reroute is False
    assert decision.reason == "cooldown"
    assert decision.unsafe_latched is True
    recovered = service.decide(
        mode="SAFEST",
        current_risk=0.54,
        current_eta_s=210,
        candidate_risk=0.2,
        candidate_eta_s=180,
        affected_edge_ids={"edge"},
        route_is_affected=True,
        current_level="MODERATE",
        candidate_level="LOW",
        unsafe_latched=True,
        last_rerouted_at=now - timedelta(seconds=31),
    )
    assert recovered.unsafe_latched is False


def test_bounded_slow_subscriber_preserves_critical_latest_event() -> None:
    publisher = RealtimePublisher(queue_size=4)
    route_id = "11111111-1111-4111-8111-111111111111"
    queue = publisher.subscribe(route_id)
    for score in (0.1, 0.2, 0.3, 0.4, 0.5):
        publisher.publish(
            route_id,
            "route.risk_updated",
            RouteRiskUpdatedData(riskScore=score, riskLevel="LOW", riskConfidence=1),
            risk_revision=1,
        )
    assert queue.qsize() <= 4
    assert queue.get_nowait().sequence > 1


def test_sse_endpoint_validates_uuid_and_active_route(client) -> None:
    invalid = client.get("/api/v1/routes/not-a-uuid/events?token=test_token_123")
    missing = client.get(
        "/api/v1/routes/11111111-1111-4111-8111-111111111111/events?token=test_token_11111111-1111-4111-8111-111111111111"
    )

    assert invalid.status_code == 422
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_flash_flood_reroutes_once_with_distinct_identity_and_complete_payload() -> None:
    old_id = "11111111-1111-4111-8111-111111111111"
    new_id = "22222222-2222-4222-8222-222222222222"
    registry = ActiveRouteRegistry()
    registry.register(
        ActiveRoute(
            old_id,
            "graph-fixture",
            "SAFEST",
            (0, 0),
            (3, 0),
            ["AB", "BC", "CD"],
            0.1,
            "LOW",
            180,
            risk_confidence=0.9,
        )
    )
    publisher = RealtimePublisher()
    queue = publisher.subscribe(old_id)
    calls = 0

    async def evaluate(route: ActiveRoute, revision: int) -> RouteEvaluation:
        return RouteEvaluation(0.85, "SEVERE", 0.95, [])

    async def calculate(route: ActiveRoute, revision: int) -> ReplacementRoute:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return ReplacementRoute(
            new_id,
            ["AE", "EF", "FD"],
            0.2,
            "LOW",
            0.9,
            210,
            600,
            {"type": "LineString", "coordinates": [[0, 0], [0, 1], [3, 0]]},
            [],
        )

    coordinator = RealtimeRerouteCoordinator(
        registry, publisher, RouteReroutingService(cooldown_seconds=30), evaluate, calculate
    )
    await asyncio.gather(
        coordinator.risk_edges_changed(1, {"BC"}),
        coordinator.risk_edges_changed(1, {"BC"}),
    )
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert calls == coordinator.reroute_count == 1
    assert [event.eventType for event in events] == [
        "route.invalidated",
        "route.rerouting",
        "route.recalculated",
    ]
    recalculated = events[-1].data
    assert recalculated.oldRouteId == old_id
    assert recalculated.newRouteId == new_id
    assert recalculated.geometry["type"] == "LineString"
    assert recalculated.etaDeltaSeconds == 30
    assert recalculated.riskReduction == pytest.approx(0.65)
    assert registry.get(old_id) is None
    assert registry.get(new_id) is not None


@pytest.mark.asyncio
async def test_sensor_outage_updates_confidence_without_forced_reroute() -> None:
    route_id = "33333333-3333-4333-8333-333333333333"
    registry = ActiveRouteRegistry()
    registry.register(
        ActiveRoute(
            route_id,
            "graph",
            "SAFEST",
            (0, 0),
            (1, 1),
            ["edge"],
            0.3,
            "MODERATE",
            120,
            risk_confidence=0.9,
        )
    )
    publisher = RealtimePublisher()
    queue = publisher.subscribe(route_id)

    async def evaluate(route: ActiveRoute, revision: int) -> RouteEvaluation:
        return RouteEvaluation(0.3, "MODERATE", 0.2, [])

    async def calculate(route: ActiveRoute, revision: int) -> ReplacementRoute | None:
        raise AssertionError("sensor outage must not start rerouting")

    coordinator = RealtimeRerouteCoordinator(
        registry, publisher, RouteReroutingService(), evaluate, calculate
    )
    await coordinator.risk_edges_changed(1, {"edge"})
    event = queue.get_nowait()
    assert event.eventType == "route.risk_updated"
    assert event.data.riskConfidence == 0.2
    assert coordinator.reroute_count == 0


@pytest.mark.asyncio
async def test_no_alternative_preserves_current_route_and_emits_failure() -> None:
    route_id = "44444444-4444-4444-8444-444444444444"
    registry = ActiveRouteRegistry()
    registry.register(
        ActiveRoute(route_id, "graph", "SAFEST", (0, 0), (1, 1), ["edge"], 0.2, "LOW", 120)
    )
    publisher = RealtimePublisher()
    queue = publisher.subscribe(route_id)

    async def evaluate(route: ActiveRoute, revision: int) -> RouteEvaluation:
        return RouteEvaluation(0.9, "SEVERE", 0.8, [])

    async def calculate(route: ActiveRoute, revision: int) -> ReplacementRoute | None:
        return None

    coordinator = RealtimeRerouteCoordinator(
        registry, publisher, RouteReroutingService(), evaluate, calculate
    )
    await coordinator.risk_edges_changed(1, {"edge"})
    events = [queue.get_nowait() for _ in range(3)]
    assert [event.eventType for event in events] == [
        "route.invalidated",
        "route.rerouting",
        "route.reroute_failed",
    ]
    assert registry.get(route_id) is not None
    assert events[-1].data.remainsTraversable is True

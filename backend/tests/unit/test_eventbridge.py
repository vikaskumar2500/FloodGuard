"""Offline routing, fan-out, transport integration, and failure semantics for Phase 15."""

import asyncio
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from simulations.models import EventType, SimulationEvent
from simulations.sinks.sqs import SqsSimulationSink

from app.core.config import Settings
from app.main import create_app
from app.messaging.consumer import HandlerRegistry
from app.messaging.envelope import TransportEnvelope
from app.messaging.eventbridge.adapter import EventBridgeSqsMessageAdapter
from app.messaging.eventbridge.memory import (
    InMemoryAuditTarget,
    InMemoryEventBridge,
    SqsTarget,
    matches,
)
from app.messaging.eventbridge.publisher import (
    MAX_REQUEST_BYTES,
    EventBridgeEventPublisher,
    entry_size,
)
from app.messaging.eventbridge.rules import processing_rules
from app.messaging.handlers import (
    SensorObservationHandler,
    SimulationEventHandler,
    WeatherObservedHandler,
)
from app.messaging.idempotency import RedisIdempotencyStore
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import (
    EVENT_SENSOR_HEALTH,
    EVENT_SENSOR_WATER_DEPTH,
    EVENT_SIMULATION_EMITTED,
    EVENT_WEATHER_OBSERVED,
    create_sensor_water_depth_event,
    create_weather_observed_event,
)
from app.messaging.serializer import DeserializationError, EventSerializer
from app.messaging.sqs.client import InMemorySqsTransport
from app.messaging.sqs.consumer import SqsEventConsumer
from app.realtime.coordinator import RuntimeRiskState
from app.realtime.event_bus import InMemoryEventBus
from tests.unit.test_messaging import _FakeRedis

BUS = "floodguard-dev-events"
QUEUE = "memory://floodguard-events-standard"


def weather(**kwargs):
    return create_weather_observed_event(
        latitude=0,
        longitude=0,
        rainfall_rate_mm_h=60,
        road_edge_ids=["edge-1"],
        correlation_id="phase15-correlation",
        causation_id="phase15-cause",
        **kwargs,
    )


def pipeline():
    metrics = MessagingMetrics()
    sqs = InMemorySqsTransport()
    bridge = InMemoryEventBridge(metrics)
    audit = InMemoryAuditTarget()
    bridge.configure_processing(BUS, SqsTarget(sqs, QUEUE), audit)
    publisher = EventBridgeEventPublisher(bridge, BUS, metrics=metrics)
    return metrics, sqs, bridge, audit, publisher


def consumer(sqs, metrics, registry):
    return SqsEventConsumer(
        sqs,
        QUEUE,
        registry,
        RedisIdempotencyStore(_FakeRedis(), fallback_mode="REJECT"),
        metrics=metrics,
        wait_time_seconds=0,
    )


@pytest.mark.parametrize(
    "event_type,rule",
    [
        (EVENT_WEATHER_OBSERVED, "environment-events"),
        (EVENT_SENSOR_WATER_DEPTH, "sensor-events"),
        (EVENT_SENSOR_HEALTH, "sensor-events"),
        (EVENT_SIMULATION_EMITTED, "simulation-events"),
        ("unknown.event", None),
        ("risk.edges_changed", None),
        ("incident.reported", None),
    ],
)
def test_rule_isolation(event_type, rule):
    event = {"source": "com.floodguard", "detail-type": event_type, "detail": {"eventVersion": 1}}
    matched = [name for name, pattern in processing_rules().items() if matches(pattern, event)]
    assert matched == ([f"floodguard-v1-{rule}"] if rule else [])
    event["source"] = "wrong.source"
    assert not any(matches(p, event) for p in processing_rules().values())
    event["source"] = "com.floodguard"
    event["detail"]["eventVersion"] = 2
    assert not any(matches(p, event) for p in processing_rules().values())


async def test_fanout_identity_and_adapter():
    metrics, sqs, bridge, audit, pub = pipeline()
    event = weather(event_id="phase15-weather-001")
    result = await pub.publish(event)
    assert result.success and result.eventbridge_event_id and result.message_id is None
    assert sqs.get_queue_length(QUEUE) == len(audit.events) == 1
    messages = await sqs.receive_messages(queue_url=QUEUE, wait_time_seconds=0)
    message = messages[0]
    adapted = EventBridgeSqsMessageAdapter().deserialize(message["Body"])
    assert adapted.envelope.to_domain() == event
    assert adapted.eventbridge_event_id == result.eventbridge_event_id
    assert adapted.eventbridge_event_id != event.event_id != message["MessageId"]
    assert audit.events[0] == adapted.envelope.to_dict()
    assert metrics.eventbridge_fanout_total == 2
    print(
        "FANOUT",
        json.dumps(
            {
                "targets": [d["target"] for d in bridge.deliveries],
                "eventId": event.event_id,
                "correlationId": event.correlation_id,
            }
        ),
    )


async def test_audit_failure_does_not_block_sqs_and_cannot_mutate_other_target():
    metrics, sqs, bridge, _, pub = pipeline()

    async def broken(event):
        event["detail"]["eventId"] = "mutated"
        raise RuntimeError("audit down")

    pattern = processing_rules()["floodguard-v1-environment-events"]
    bridge.put_rule(
        BUS,
        "floodguard-v1-environment-events",
        pattern,
        {"broken-audit": broken, "processing-sqs": SqsTarget(sqs, QUEUE)},
    )
    event = weather()
    assert (await pub.publish(event)).success
    assert sqs.get_queue_length(QUEUE) == 1
    msg = (await sqs.receive_messages(queue_url=QUEUE, wait_time_seconds=0))[0]
    assert (
        EventBridgeSqsMessageAdapter().deserialize(msg["Body"]).envelope.event_id == event.event_id
    )
    assert metrics.eventbridge_target_errors_total == 1
    assert metrics.eventbridge_fanout_total == 1


async def test_unknown_and_sensor_delivery_isolation():
    metrics, sqs, _, audit, pub = pipeline()
    assert (await pub.publish(replace(weather(), event_type="unsupported.event"))).success
    assert sqs.get_queue_length(QUEUE) == 0
    assert metrics.eventbridge_unmatched_total == 1
    assert (await pub.publish(create_sensor_water_depth_event("s1", "edge-1", 40))).success
    assert sqs.get_queue_length(QUEUE) == 1
    assert audit.events == []


async def test_partial_batch_failure_eight_success_two_failure():
    metrics, sqs, bridge, audit, pub = pipeline()
    events = [weather(event_id=f"partial-{i}") for i in range(10)]
    bridge.fail_event_ids = {events[2].event_id, events[7].event_id}
    results = await pub.publish_batch(events)
    assert [r.event_id for r in results] == [e.event_id for e in events]
    assert [i for i, r in enumerate(results) if not r.success] == [2, 7]
    assert all(r.failed_entry_count == 2 for r in results)
    assert results[2].error_code == results[7].error_code == "InternalFailure"
    assert len(bridge.requests) == 1
    assert sqs.get_queue_length(QUEUE) == len(audit.events) == 8
    assert metrics.eventbridge_partial_failure_total == 1
    assert metrics.eventbridge_publish_success_total == 8
    assert metrics.eventbridge_publish_failure_total == 2


async def test_api_failure_no_fallback():
    metrics, sqs, bridge, audit, pub = pipeline()
    bridge.fail_api = True
    results = await pub.publish_batch([weather(), weather()])
    assert all(not r.success and r.error_code == "ConnectionError" for r in results)
    assert sqs.get_queue_length(QUEUE) == len(audit.events) == 0
    assert metrics.eventbridge_publish_failure_total == 2


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"Entries": [], "FailedEntryCount": 0},
        {"Entries": [{"EventId": "id"}], "FailedEntryCount": 1},
        {"Entries": [{}], "FailedEntryCount": 1},
    ],
)
async def test_invalid_api_response_not_reported_success(response):
    client = AsyncMock()
    client.put_events.return_value = response
    result = await EventBridgeEventPublisher(client, BUS).publish(weather())
    assert not result.success


async def test_batch_size_utf8_limit_serialization_and_order():
    metrics, _, bridge, _, pub = pipeline()
    events = [weather(event_id=f"size-{i}") for i in range(23)]
    events[3] = replace(events[3], payload={"text": "🌧" * 270_000})
    events[4] = replace(events[4], payload={"unserializable": object()})
    events[5] = replace(events[5], payload={"text": "x" * 600_000})
    events[6] = replace(events[6], payload={"text": "x" * 600_000})
    results = await pub.publish_batch(events)
    assert [r.event_id for r in results] == [e.event_id for e in events]
    assert results[3].error_code == "EventTooLarge"
    assert results[4].error_code == "SerializationError"
    assert sum(r.success for r in results) == 21
    assert all(
        len(r) <= 10 and sum(map(entry_size, r)) < MAX_REQUEST_BYTES for r in bridge.requests
    )
    assert metrics.eventbridge_oversized_total == 1
    assert await pub.publish_batch([]) == []


def outer():
    return {
        "version": "0",
        "id": "bridge-id",
        "source": "com.floodguard",
        "detail-type": EVENT_WEATHER_OBSERVED,
        "account": "000000000000",
        "region": "ap-south-1",
        "time": "2030-01-01T00:00:00Z",
        "resources": [],
        "detail": TransportEnvelope.from_domain(weather()).to_dict(),
    }


@pytest.mark.parametrize(
    "change",
    [
        {"version": "1"},
        {"id": None},
        {"source": ""},
        {"time": "bad"},
        {"time": "2030-01-01"},
        {"resources": None},
        {"detail": "{}"},
        {"detail": {}},
        {"detail-type": "wrong"},
        {"eventId": "ambiguous"},
    ],
)
async def test_malformed_outer_no_handler(change):
    metrics, sqs, _, _, _ = pipeline()
    data = outer() | change
    handler = AsyncMock()
    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, handler)
    c = consumer(sqs, metrics, registry)
    await sqs.send_message(queue_url=QUEUE, message_body=json.dumps(data))
    assert await c.poll_once() == 0
    handler.handle.assert_not_called()
    assert metrics.eventbridge_adapter_errors_total == 1


def test_adapter_preserves_canonical_time_and_direct_sqs():
    data = outer()
    adapter = EventBridgeSqsMessageAdapter()
    wrapped = adapter.deserialize(json.dumps(data))
    direct = adapter.deserialize(json.dumps(data["detail"]))
    assert wrapped.envelope == direct.envelope
    assert wrapped.envelope.occurred_at.year != 2030
    assert direct.eventbridge_event_id is None
    with pytest.raises(DeserializationError):
        adapter.deserialize('{"detail":{},"eventId":"ambiguous"}')


@pytest.mark.parametrize("kind", ["weather", "sensor"])
async def test_environment_duplicate_and_out_of_order(kind):
    metrics, sqs, _, _, pub = pipeline()
    risk = RuntimeRiskState()
    registry = HandlerRegistry()
    if kind == "weather":
        handler = WeatherObservedHandler(risk, InMemoryEventBus())
        newer = weather()
        older = replace(
            newer,
            event_id="older",
            occurred_at=newer.occurred_at - timedelta(minutes=5),
            payload={"rainfallRateMmPerHour": 0, "roadEdgeIds": ["edge-1"]},
        )
    else:
        handler = SensorObservationHandler(risk, InMemoryEventBus())
        newer = create_sensor_water_depth_event("s1", "edge-1", 40)
        older = replace(
            newer,
            event_id="older",
            occurred_at=newer.occurred_at - timedelta(minutes=5),
            payload={"waterDepthCm": 0, "roadEdgeId": "edge-1"},
        )
    tracked = AsyncMock(wraps=handler.handle)
    handler.handle = tracked
    registry.register(newer.event_type, handler)
    c = consumer(sqs, metrics, registry)
    await pub.publish(newer)
    await c.poll_once()
    await pub.publish(newer)
    await c.poll_once()
    assert tracked.call_count == 1 and risk.revision == 1
    assert metrics.sqs_duplicates_total == 1
    await pub.publish(older)
    await c.poll_once()
    assert risk._scores["edge-1"][1:] == ("SEVERE", True)
    assert risk.revision == 1


@pytest.mark.parametrize("mode", ["IN_PROCESS", "SQS", "EVENTBRIDGE"])
def test_application_transport_selection_and_nonblocking_startup(monkeypatch, mode):
    from app.messaging.publisher import InMemoryEventPublisher
    from app.messaging.sqs.publisher import SqsEventPublisher

    _, sqs, bridge, _, _ = pipeline()
    monkeypatch.setattr("app.messaging.factory.Boto3SqsClient", lambda **kw: sqs)
    monkeypatch.setattr("app.main.Boto3SqsClient", lambda **kw: sqs)
    monkeypatch.setattr("app.messaging.factory.Boto3EventBridgeClient", lambda *args: bridge)

    # Exercise the real start/stop methods without a hot loop from zero-wait in-memory SQS.
    async def idle_poll(self):
        await asyncio.sleep(0.01)
        return 0

    monkeypatch.setattr(SqsEventConsumer, "poll_once", idle_poll)
    monkeypatch.setattr(
        "app.services.health.HealthService.readiness",
        AsyncMock(return_value=type("Health", (), {"ready": True})()),
    )
    config = Settings(
        _env_file=None,
        app_env="test",
        cache_enabled=False,
        event_transport=mode,
        sqs_enabled=True,
        eventbridge_enabled=True,
    )
    with TestClient(create_app(config)) as client:
        cls = {
            "IN_PROCESS": InMemoryEventPublisher,
            "SQS": SqsEventPublisher,
            "EVENTBRIDGE": EventBridgeEventPublisher,
        }[mode]
        assert isinstance(client.app.state.event_publisher, cls)
        assert (client.app.state.sqs_consumer is not None) == (mode != "IN_PROCESS")


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {"eventbridge_enabled": True},
        {"eventbridge_enabled": True, "sqs_enabled": True, "eventbridge_bus_name": "default"},
    ],
)
def test_invalid_eventbridge_configuration(settings):
    with pytest.raises(ValueError):
        Settings(_env_file=None, event_transport="EVENTBRIDGE", **settings)


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        app_env="test",
        use_fixture_routing=True,
        enable_simulation_api=True,
        cache_enabled=False,
    )


def test_eventbridge_simulator_to_reroute_duplicate_and_late(client):
    runtime = client.app.state.runtime
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
    queue = runtime.realtime_publisher.subscribe(response.json()["routeId"])
    metrics, sqs, _, _, pub = pipeline()
    registry = HandlerRegistry()
    handler = SimulationEventHandler(runtime)
    tracked = AsyncMock(wraps=handler.handle)
    handler.handle = tracked
    registry.register(EVENT_SIMULATION_EMITTED, handler)
    c = consumer(sqs, metrics, registry)
    sink = SqsSimulationSink(pub)
    event = SimulationEvent(
        event_id=uuid4(),
        scenario_id="phase15",
        sequence=1,
        event_type=EventType.FLOOD_ZONE_UPDATED,
        occurred_at=datetime.now(UTC),
        payload={
            "zone_id": "top",
            "severity": "SEVERE",
            "risk_score": 0.95,
            "confidence": 0.9,
            "target_edge_ids": [f"fixture-top-{i}" for i in (1, 2, 3)],
        },
    )
    start = time.perf_counter()
    sink.emit(event)
    assert runtime.runtime_risk_state.revision == 0
    assert asyncio.run(c.poll_once()) == 1
    elapsed = (time.perf_counter() - start) * 1000
    assert runtime.runtime_risk_state.revision == 1
    messages = [queue.get_nowait() for _ in range(3)]
    assert [m.eventType for m in messages] == [
        "route.invalidated",
        "route.rerouting",
        "route.recalculated",
    ]
    assert messages[-1].data.geometry["type"] == "LineString"
    assert runtime.reroute_coordinator.reroute_count == 1
    authoritative_scores = dict(runtime.runtime_risk_state._scores)
    sink.emit(event)
    assert asyncio.run(c.poll_once()) == 0
    assert tracked.call_count == 1 and metrics.sqs_duplicates_total == 1
    late = replace(
        event,
        event_id=uuid4(),
        occurred_at=event.occurred_at - timedelta(minutes=5),
        payload=event.payload | {"severity": "LOW", "risk_score": 0.0},
    )
    sink.emit(late)
    asyncio.run(c.poll_once())
    assert runtime.runtime_risk_state.revision == 1
    assert runtime.runtime_risk_state._scores == authoritative_scores
    assert any(value[1] == "SEVERE" for value in authoritative_scores.values())
    assert runtime.reroute_coordinator.reroute_count == 1 and queue.empty()
    print(f"EMULATOR reroute_end_to_end_ms={elapsed:.3f}")


async def test_burst_and_batch_benchmark():
    events = [weather(event_id=f"burst-{i}") for i in range(100)]
    metrics, sqs, bridge, audit, pub = pipeline()
    start = time.perf_counter()
    for event in events:
        assert (await pub.publish(event)).success
    single_ms = (time.perf_counter() - start) * 1000
    assert len(bridge.requests) == 100
    metrics, sqs, bridge, audit, pub = pipeline()
    start = time.perf_counter()
    results = await pub.publish_batch(events)
    batch_ms = (time.perf_counter() - start) * 1000
    assert len(bridge.requests) == 10 and all(r.success for r in results)
    assert sqs.get_queue_length(QUEUE) == len(audit.events) == 100
    risk = RuntimeRiskState()
    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, WeatherObservedHandler(risk, InMemoryEventBus()))
    c = consumer(sqs, metrics, registry)
    start = time.perf_counter()
    for _ in range(10):
        assert await c.poll_once() == 10
    consume_ms = (time.perf_counter() - start) * 1000
    assert metrics.sqs_messages_processed_total == 100
    assert metrics.sqs_duplicates_total == metrics.sqs_handler_errors_total == 0
    assert (
        metrics.eventbridge_events_routed_total == 100 and metrics.eventbridge_fanout_total == 200
    )
    print(
        "EMULATOR_BURST",
        json.dumps(
            {
                "events": 100,
                "single_publish_total_ms": round(single_ms, 3),
                "batch_publish_total_ms": round(batch_ms, 3),
                "consume_total_ms": round(consume_ms, 3),
                "accepted": 100,
                "routed": 100,
                "processed": 100,
                "duplicates": 0,
                "failures": 0,
            }
        ),
    )


async def test_stage_latency_and_weather_poller():
    from app.environment.polling import EnvironmentalPollingService
    from app.environment.providers.mock import MockEnvironmentalProvider
    from app.environment.service import EnvironmentalService

    metrics, sqs, bridge, _, pub = pipeline()
    risk = RuntimeRiskState()
    service = EnvironmentalService(
        provider=MockEnvironmentalProvider(rainfall_mm_per_hour=60), redis=None
    )
    poller = EnvironmentalPollingService(
        service, risk, locations=[(0, 0)], target_edge_ids=["edge-1"], event_publisher=pub
    )
    registry = HandlerRegistry()
    actual = WeatherObservedHandler(risk, InMemoryEventBus())
    times = {}

    async def handle(event):
        times["handler"] = time.perf_counter()
        await actual.handle(event)
        times["risk"] = time.perf_counter()

    registry.register(
        EVENT_WEATHER_OBSERVED, type("Handler", (), {"handle": staticmethod(handle)})()
    )
    c = consumer(sqs, metrics, registry)
    times["start"] = time.perf_counter()
    await poller.poll_once()
    times["published"] = time.perf_counter()
    assert sqs.get_queue_length(QUEUE) == 1 and risk.revision == 0
    await c.poll_once()
    assert risk.revision == 1
    print(
        "EMULATOR_LATENCY",
        json.dumps(
            {
                "publish_ms": round((times["published"] - times["start"]) * 1000, 3),
                "eventbridge_to_sqs_target_ms": round(bridge.deliveries[0]["latency_ms"], 3),
                "sqs_to_handler_ms": round((times["handler"] - times["published"]) * 1000, 3),
                "handler_to_risk_ms": round((times["risk"] - times["handler"]) * 1000, 3),
                "end_to_end_ms": round((times["risk"] - times["start"]) * 1000, 3),
            }
        ),
    )


async def test_poller_failure_does_not_apply_risk_or_mark_published():
    from app.environment.polling import EnvironmentalPollingService
    from app.environment.providers.mock import MockEnvironmentalProvider
    from app.environment.service import EnvironmentalService

    _, sqs, bridge, _, pub = pipeline()
    risk = RuntimeRiskState()
    poller = EnvironmentalPollingService(
        EnvironmentalService(
            provider=MockEnvironmentalProvider(rainfall_mm_per_hour=60), redis=None
        ),
        risk,
        locations=[(0, 0)],
        event_publisher=pub,
    )
    bridge.fail_api = True
    await poller.poll_once()
    assert risk.revision == 0 and sqs.get_queue_length(QUEUE) == 0
    bridge.fail_api = False
    await poller.poll_once()
    assert sqs.get_queue_length(QUEUE) == 1


async def test_sdk_mapping_bus_arn_and_configured_region(monkeypatch):
    from botocore.stub import Stubber

    from app.messaging.eventbridge.client import Boto3EventBridgeClient

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "offline-test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "offline-test")
    client = Boto3EventBridgeClient("ap-south-1")
    event = weather()
    bus = "arn:aws:events:ap-south-1:123456789012:event-bus/floodguard-dev-events"
    entry = {
        "Source": "com.floodguard",
        "DetailType": event.event_type,
        "Detail": EventSerializer.serialize(TransportEnvelope.from_domain(event)),
        "EventBusName": bus,
    }
    with Stubber(client.client) as stub:
        stub.add_response(
            "put_events",
            {"FailedEntryCount": 0, "Entries": [{"EventId": "aws-id"}]},
            {"Entries": [entry]},
        )
        result = await EventBridgeEventPublisher(client, bus).publish(event)
        assert result.success and result.eventbridge_event_id == "aws-id"
        assert client.client.meta.region_name == "ap-south-1"
        stub.assert_no_pending_responses()


def test_resource_spec_matches_local_rules_and_least_privilege():
    from scripts.bootstrap_eventbridge import resource_spec

    arn = "arn:aws:sqs:ap-south-1:123456789012:floodguard-dev-events-standard"
    spec = resource_spec(BUS, "com.floodguard", arn)
    assert {r["Name"]: r["EventPattern"] for r in spec["Rules"]} == processing_rules()
    assert all(r["Targets"] == [{"Id": "processing-sqs", "Arn": arn}] for r in spec["Rules"])
    assert spec["ProducerPolicy"]["Statement"][0]["Action"] == "events:PutEvents"
    for statement in spec["QueuePolicy"]["Statement"]:
        assert statement["Principal"] == {"Service": "events.amazonaws.com"}
        assert statement["Action"] == "sqs:SendMessage"
        assert statement["Resource"] == arn
        assert f":rule/{BUS}/floodguard-v1-" in statement["Condition"]["ArnEquals"]["aws:SourceArn"]
    assert "*" not in json.dumps(spec)


def test_bootstrap_idempotent_preserves_unrelated_permissions():
    from unittest.mock import Mock

    from scripts.bootstrap_eventbridge import apply_spec, resource_spec

    arn = "arn:aws:sqs:ap-south-1:123456789012:floodguard-dev-events-standard"
    spec = resource_spec(BUS, "com.floodguard", arn)
    unrelated = {"Sid": "UnrelatedPermission", "Action": "sqs:GetQueueAttributes"}
    attributes = {"QueueArn": arn, "Policy": json.dumps({"Statement": [unrelated]})}
    events, sqs = Mock(), Mock()
    sqs.get_queue_attributes.return_value = {"Attributes": attributes}
    events.put_targets.return_value = {"FailedEntryCount": 0}

    def set_attributes(**kwargs):
        attributes.update(kwargs["Attributes"])

    sqs.set_queue_attributes.side_effect = set_attributes
    apply_spec(spec, events, sqs, QUEUE)
    first = attributes["Policy"]
    apply_spec(spec, events, sqs, QUEUE)
    assert attributes["Policy"] == first
    assert len(json.loads(first)["Statement"]) == 4
    assert unrelated in json.loads(first)["Statement"]
    events.create_event_bus.assert_not_called()
    events.put_targets.return_value = {
        "FailedEntryCount": 1,
        "FailedEntries": [{"Id": "processing-sqs"}],
    }
    with pytest.raises(RuntimeError):
        apply_spec(spec, events, sqs, QUEUE)


async def test_structured_trace_identifiers_are_separate(caplog):
    import logging

    from app.core.logging import JsonFormatter

    metrics, sqs, _, _, pub = pipeline()
    event = weather()
    registry = HandlerRegistry()
    registry.register(
        event.event_type, WeatherObservedHandler(RuntimeRiskState(), InMemoryEventBus())
    )
    # App logging normally does not propagate; attach the test capture handler directly.
    logger = logging.getLogger("floodguard")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger="floodguard"):
            result = await pub.publish(event)
            await consumer(sqs, metrics, registry).poll_once()
    finally:
        logger.removeHandler(caplog.handler)
    records = [json.loads(JsonFormatter().format(r)) for r in caplog.records]
    published = next(r for r in records if r["event"] == "eventbridge_publish")
    processed = next(r for r in records if r["event"] == "sqs_message_processed_success")
    assert (
        published["eventbridge_event_id"]
        == processed["eventbridge_event_id"]
        == result.eventbridge_event_id
    )
    assert processed["domain_event_id"] == event.event_id
    assert processed["correlation_id"] == event.correlation_id
    assert (
        len({processed["eventbridge_event_id"], processed["sqs_message_id"], event.event_id}) == 3
    )
    assert "payload" not in published and "payload" not in processed


async def test_simulator_publisher_failure_propagates():
    _, _, bridge, _, pub = pipeline()
    bridge.fail_api = True
    sink = SqsSimulationSink(pub)
    event = SimulationEvent(
        uuid4(), "phase15", 1, EventType.FLOOD_ZONE_UPDATED, datetime.now(UTC), {}
    )
    with pytest.raises(RuntimeError, match="publication failed"):
        await sink.emit_async(event)
    assert sink.events_emitted == 0

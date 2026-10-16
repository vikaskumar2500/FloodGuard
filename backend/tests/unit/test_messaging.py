"""Unit and integration tests for Phase 14: AWS SQS Asynchronous Event Processing.

Tests cover:
- Transport envelope serialization and roundtrip
- Event validation and version enforcement
- Malformed payload resilience (consumer does not crash)
- Unknown event type resilience
- Correlation and causation ID propagation
- Redis idempotency store lifecycle (ACQUIRED, PROCESSING, COMPLETED, release)
- Degraded idempotency fallback
- At-least-once delivery: redelivery on handler failure, delete only on success
- Out-of-order event suppression (CRITICAL INVARIANT 5)
- Bounded concurrency under burst load (100 messages)
- SQS-to-rerouting end-to-end integration (SQS -> Handler -> RiskState -> Bus -> Coordinator -> SSE)
- SQS simulation sink
- Latency benchmarks
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from simulations.models import EventType, SimulationEvent
from simulations.sinks.sqs import SqsSimulationSink

from app.messaging.consumer import DomainEventHandler, HandlerRegistry
from app.messaging.envelope import TransportEnvelope
from app.messaging.handlers import (
    SensorObservationHandler,
    SimulationEventHandler,
    WeatherObservedHandler,
)
from app.messaging.idempotency import (
    IdempotencyStatus,
    IdempotencyStoreUnavailableError,
    RedisIdempotencyStore,
)
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import (
    EVENT_SENSOR_WATER_DEPTH,
    EVENT_SIMULATION_EMITTED,
    EVENT_WEATHER_OBSERVED,
    DomainEvent,
    create_weather_observed_event,
)
from app.messaging.serializer import (
    DeserializationError,
    EventSerializer,
    UnsupportedVersionError,
)
from app.messaging.sqs.client import InMemorySqsTransport
from app.messaging.sqs.consumer import SqsEventConsumer
from app.messaging.sqs.publisher import SqsEventPublisher
from app.realtime.coordinator import RuntimeRiskState
from app.realtime.event_bus import InMemoryEventBus

# =====================================================================
# 1. ENVELOPE SERIALIZATION & VALIDATION
# =====================================================================


def test_envelope_serialization_roundtrip():
    """Verifies that DomainEvent serialized into TransportEnvelope deserializes identically."""
    event = create_weather_observed_event(
        latitude=37.7749,
        longitude=-122.4194,
        rainfall_rate_mm_h=15.5,
        temperature_c=18.0,
        correlation_id="corr-123",
        causation_id="cause-456",
    )
    envelope = TransportEnvelope.from_domain_event(event)
    raw_json = EventSerializer.serialize(envelope)

    restored = EventSerializer.deserialize(raw_json)
    assert restored.event_id == event.event_id
    assert restored.event_type == EVENT_WEATHER_OBSERVED
    assert restored.event_version == 1
    assert restored.correlation_id == "corr-123"
    assert restored.causation_id == "cause-456"
    assert restored.payload["latitude"] == 37.7749
    assert restored.payload["rainfallRateMmPerHour"] == 15.5


def test_unsupported_version_rejection():
    """Verifies that envelopes with unsupported versions raise UnsupportedVersionError."""
    payload = {
        "eventId": str(uuid4()),
        "eventType": EVENT_WEATHER_OBSERVED,
        "eventVersion": 99,  # Unsupported version
        "occurredAt": datetime.now(UTC).isoformat(),
        "producer": "weather-service",
        "correlationId": str(uuid4()),
        "causationId": str(uuid4()),
        "payload": {},
    }
    raw_json = json.dumps(payload)
    with pytest.raises(UnsupportedVersionError) as exc_info:
        EventSerializer.deserialize(raw_json)
    assert "Unsupported event version 99" in str(exc_info.value)


def test_missing_required_fields_rejection():
    """Verifies that invalid envelope JSON missing required keys raises DeserializationError."""
    bad_payloads = [
        {},
        {"eventId": "abc"},
        {"eventId": "abc", "eventType": "test"},
        "not-even-json-{}",
    ]
    for bad in bad_payloads:
        with pytest.raises(DeserializationError):
            EventSerializer.deserialize(bad if isinstance(bad, str) else json.dumps(bad))


# =====================================================================
# 2. IDEMPOTENCY STORE
# =====================================================================


class _FakeRedis:
    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self._store:
            return False
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = ex
        return True

    async def delete(self, key: str):
        return 1 if self._store.pop(key, None) is not None else 0

    async def eval(self, script: str, numkeys: int, *args):
        key = args[0]
        import json

        if len(args) == 4:  # mark_completed
            payload = args[1]
            token = args[2]
            ex = args[3]
            current = self._store.get(key)
            if current:
                decoded = json.loads(current)
                if decoded.get("token") == token or decoded.get("state") == "COMPLETED":
                    self._store[key] = payload
                    self._ttls[key] = ex
                    return 1
                return 0
            self._store[key] = payload
            self._ttls[key] = ex
            return 1
        elif len(args) == 2:  # release
            token = args[1]
            current = self._store.get(key)
            if current:
                decoded = json.loads(current)
                if decoded.get("token") == token:
                    self._store.pop(key, None)
                    return 1
            return 0


@pytest.mark.asyncio
async def test_idempotency_lifecycle():
    """Tests ACQUIRED -> COMPLETED -> ALREADY_COMPLETED lifecycle with lease."""
    fake_redis = _FakeRedis()
    store = RedisIdempotencyStore(fake_redis, ttl_seconds=86400, lease_seconds=60)
    event_id = str(uuid4())

    # 1. First attempt acquires lease
    status1 = await store.try_acquire(event_id, correlation_id="c-1")
    assert status1 == IdempotencyStatus.ACQUIRED

    # 2. Second concurrent attempt while still processing is IN_PROGRESS
    status2 = await store.try_acquire(event_id, correlation_id="c-1")
    assert status2 == IdempotencyStatus.IN_PROGRESS

    # 3. Mark completed
    await store.mark_completed(event_id, correlation_id="c-1")

    # 4. Third attempt after completion is ALREADY_COMPLETED
    status3 = await store.try_acquire(event_id, correlation_id="c-1")
    assert status3 == IdempotencyStatus.ALREADY_COMPLETED


@pytest.mark.asyncio
async def test_idempotency_release_on_failure():
    """Tests lease release when processing fails, allowing retry."""
    fake_redis = _FakeRedis()
    store = RedisIdempotencyStore(fake_redis, ttl_seconds=86400, lease_seconds=60)
    event_id = str(uuid4())

    status = await store.try_acquire(event_id)
    assert status == IdempotencyStatus.ACQUIRED

    # Release lease on handler error
    await store.release(event_id)

    # Next attempt can acquire lease again for retry
    status_retry = await store.try_acquire(event_id)
    assert status_retry == IdempotencyStatus.ACQUIRED


@pytest.mark.asyncio
async def test_idempotency_degraded_fallback():
    """Tests fallback behavior when Redis is unavailable."""
    # When fallback_mode is DEGRADED_PROCESS, lease is granted with warning
    store_degraded = RedisIdempotencyStore(None, fallback_mode="DEGRADED_PROCESS")
    status = await store_degraded.try_acquire("evt-123")
    assert status == IdempotencyStatus.ACQUIRED

    # When fallback_mode is REJECT, raises exception
    store_reject = RedisIdempotencyStore(None, fallback_mode="REJECT")
    with pytest.raises(IdempotencyStoreUnavailableError):
        await store_reject.try_acquire("evt-123")


# =====================================================================
# 3. AT-LEAST-ONCE DELIVERY & RETRY (CRITICAL INVARIANTS 1 & 2)
# =====================================================================


class _FailingHandler(DomainEventHandler):
    def __init__(self, fail_count: int = 1):
        self.attempts = 0
        self.fail_count = fail_count

    async def handle(self, event: DomainEvent) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_count:
            raise RuntimeError(f"Simulated failure on attempt {self.attempts}")


@pytest.mark.asyncio
async def test_redelivery_on_handler_failure(monkeypatch):
    """CRITICAL INVARIANT 2: Message is NOT deleted until successful processing."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "sqs_retry_base_delay_seconds", 0)
    monkeypatch.setattr(settings, "sqs_retry_max_delay_seconds", 0)
    monkeypatch.setattr(settings, "sqs_retry_jitter", False)

    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/events?token=test_token_{route_id}"
    metrics = MessagingMetrics()
    fake_redis = _FakeRedis()
    store = RedisIdempotencyStore(fake_redis)

    publisher = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)
    handler = _FailingHandler(fail_count=1)

    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, handler)

    consumer = SqsEventConsumer(
        client=transport,
        queue_url=queue_url,
        registry=registry,
        idempotency_store=store,
        metrics=metrics,
        wait_time_seconds=0,
    )

    event = create_weather_observed_event(
        latitude=0.0,
        longitude=0.0,
        rainfall_rate_mm_h=5.0,
    )
    await publisher.publish(event)

    # 1. First iteration: handler fails
    processed_count = await consumer.poll_once()
    assert processed_count == 0
    assert handler.attempts == 1
    # Message should NOT be deleted, and should still be in the queue
    assert transport.get_queue_length(queue_url) == 1
    assert metrics.get_snapshot()["sqs_messages_failed"] == 1
    assert metrics.get_snapshot()["sqs_messages_deleted"] == 0

    # 2. Second iteration: retry succeeds
    processed_count = await consumer.poll_once()
    assert processed_count == 1
    assert handler.attempts == 2
    # Message should NOW be deleted from queue
    assert transport.get_queue_length(queue_url) == 0
    assert metrics.get_snapshot()["sqs_messages_processed"] == 1
    assert metrics.get_snapshot()["sqs_messages_deleted"] == 1


@pytest.mark.asyncio
async def test_idempotent_duplicate_message_skips_handler():
    """CRITICAL INVARIANT 1: Duplicate delivery executes handler only once."""
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/events?token=test_token_{route_id}"
    metrics = MessagingMetrics()
    fake_redis = _FakeRedis()
    store = RedisIdempotencyStore(fake_redis)

    call_count = 0

    class _CountingHandler(DomainEventHandler):
        async def handle(self, event: DomainEvent) -> None:
            nonlocal call_count
            call_count += 1

    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, _CountingHandler())

    consumer = SqsEventConsumer(
        client=transport,
        queue_url=queue_url,
        registry=registry,
        idempotency=store,
        metrics=metrics,
        poll_wait_seconds=0,
    )

    # Publish same event twice
    event = create_weather_observed_event(
        latitude=0.0,
        longitude=0.0,
        rainfall_rate_mm_h=5.0,
    )
    publisher = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)
    await publisher.publish(event)
    await publisher.publish(event)

    # Process first message: succeeds and completes
    await consumer.poll_once()
    assert call_count == 1

    # Process second duplicate message: skips handler, deletes duplicate from queue
    await consumer.poll_once()
    assert call_count == 1  # Still 1! Not called twice!
    assert metrics.get_snapshot()["sqs_messages_duplicated"] == 1
    assert transport.get_queue_length(queue_url) == 0


# =====================================================================
# 4. RESILIENCE: MALFORMED PAYLOADS & UNKNOWN EVENTS
# =====================================================================


@pytest.mark.asyncio
async def test_consumer_handles_malformed_json_without_crashing():
    """Verifies that corrupted JSON in SQS does not terminate the consumer."""
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/events?token=test_token_{route_id}"
    metrics = MessagingMetrics()
    consumer = SqsEventConsumer(
        client=transport,
        queue_url=queue_url,
        registry=HandlerRegistry(),
        metrics=metrics,
        wait_time_seconds=0,
    )

    # Put malformed message directly in transport
    await transport.send_message(QueueUrl=queue_url, MessageBody="{malformed json !!")

    processed = await consumer.poll_once()
    assert processed == 0
    assert metrics.get_snapshot()["sqs_messages_failed"] == 1
    # Malformed message is removed to prevent poison pill loops
    assert transport.get_queue_length(queue_url) == 0


@pytest.mark.asyncio
async def test_consumer_handles_unknown_event_type_gracefully():
    """Verifies that unknown event types are acknowledged without crashing."""
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/events?token=test_token_{route_id}"
    metrics = MessagingMetrics()
    consumer = SqsEventConsumer(
        client=transport,
        queue_url=queue_url,
        registry=HandlerRegistry(),
        metrics=metrics,
        wait_time_seconds=0,
    )

    envelope = TransportEnvelope(
        event_id=str(uuid4()),
        event_type="unknown.event.type",
        event_version=1,
        occurred_at=datetime.now(UTC),
        producer="test",
        correlation_id=str(uuid4()),
        causation_id=str(uuid4()),
        payload={},
    )
    await transport.send_message(
        QueueUrl=queue_url,
        MessageBody=EventSerializer.serialize(envelope),
    )

    processed = await consumer.poll_once()
    assert processed == 0
    assert transport.get_queue_length(queue_url) == 0


# =====================================================================
# 5. OUT-OF-ORDER EVENT SUPPRESSION (CRITICAL INVARIANT 5)
# =====================================================================


@pytest.mark.asyncio
async def test_out_of_order_weather_events_do_not_regress_state():
    """CRITICAL INVARIANT 5: Delayed older events must not regress newer risk state."""
    risk_state = RuntimeRiskState()
    event_bus = InMemoryEventBus()
    handler = WeatherObservedHandler(
        risk_state=risk_state,
        event_bus=event_bus,
        default_edges=["edge-1"],
    )

    now = datetime.now(UTC)
    t_newer = now
    t_older = now - timedelta(minutes=15)

    # 1. Apply newer severe rainfall (10:15)
    newer_event = DomainEvent(
        event_id="newer-1",
        event_type=EVENT_WEATHER_OBSERVED,
        occurred_at=t_newer,
        producer="weather-service",
        correlation_id="c-1",
        causation_id="cause-1",
        payload={
            "rainfallRateMmPerHour": 60.0,  # SEVERE
            "roadEdgeIds": ["edge-1"],
        },
    )
    await handler.handle(newer_event)
    edge_risk = risk_state._scores.get("edge-1")
    assert edge_risk is not None
    assert edge_risk[1] == "SEVERE"
    assert edge_risk[2] is True  # closed

    # 2. Delayed older event arrives (10:00) with 0 rainfall
    older_event = DomainEvent(
        event_id="older-2",
        event_type=EVENT_WEATHER_OBSERVED,
        occurred_at=t_older,
        producer="weather-service",
        correlation_id="c-2",
        causation_id="cause-2",
        payload={
            "rainfallRateMmPerHour": 0.0,  # LOW
            "roadEdgeIds": ["edge-1"],
        },
    )
    await handler.handle(older_event)

    # State should REMAIN SEVERE / CLOSED — NOT regressed to LOW!
    edge_risk_after = risk_state._scores.get("edge-1")
    assert edge_risk_after[1] == "SEVERE"
    assert edge_risk_after[2] is True


@pytest.mark.asyncio
async def test_out_of_order_sensor_events_do_not_regress_state():
    """CRITICAL INVARIANT 5: Delayed older sensor depth readings do not regress state."""
    risk_state = RuntimeRiskState()
    event_bus = InMemoryEventBus()
    handler = SensorObservationHandler(
        risk_state=risk_state,
        event_bus=event_bus,
    )

    now = datetime.now(UTC)
    t_newer = now
    t_older = now - timedelta(minutes=10)

    # High water depth at 10:10
    evt_high = DomainEvent(
        event_id="sensor-high",
        event_type=EVENT_SENSOR_WATER_DEPTH,
        occurred_at=t_newer,
        producer="sensor-edge",
        correlation_id="c-1",
        causation_id="cause-1",
        payload={"roadEdgeId": "edge-sensor-1", "waterDepthCm": 40.0},
    )
    await handler.handle(evt_high)
    assert risk_state._scores["edge-sensor-1"][1] == "SEVERE"

    # Delayed dry reading from 10:00
    evt_dry = DomainEvent(
        event_id="sensor-dry",
        event_type=EVENT_SENSOR_WATER_DEPTH,
        occurred_at=t_older,
        producer="sensor-edge",
        correlation_id="c-2",
        causation_id="cause-2",
        payload={"roadEdgeId": "edge-sensor-1", "waterDepthCm": 0.0},
    )
    await handler.handle(evt_dry)
    assert risk_state._scores["edge-sensor-1"][1] == "SEVERE"


# =====================================================================
# 6. BOUNDED CONCURRENCY & BURST LOAD
# =====================================================================


@pytest.mark.asyncio
async def test_bounded_concurrency_burst_processing():
    """Tests that consumer processes a burst of 100 messages within bounded concurrency limit."""
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/burst-queue"
    metrics = MessagingMetrics()
    fake_redis = _FakeRedis()
    store = RedisIdempotencyStore(fake_redis)

    active_tasks = 0
    max_active_tasks = 0
    lock = asyncio.Lock()

    class _ConcurrencyTrackingHandler(DomainEventHandler):
        async def handle(self, event: DomainEvent) -> None:
            nonlocal active_tasks, max_active_tasks
            async with lock:
                active_tasks += 1
                if active_tasks > max_active_tasks:
                    max_active_tasks = active_tasks
            await asyncio.sleep(0.005)  # brief processing delay
            async with lock:
                active_tasks -= 1

    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, _ConcurrencyTrackingHandler())

    # Concurrency limit = 5
    consumer = SqsEventConsumer(
        client=transport,
        queue_url=queue_url,
        registry=registry,
        idempotency_store=store,
        metrics=metrics,
        concurrency=5,
        max_messages=10,
        wait_time_seconds=0,
    )

    publisher = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)

    # Publish burst of 100 messages
    for i in range(100):
        evt = create_weather_observed_event(
            latitude=float(i),
            longitude=float(i),
            rainfall_rate_mm_h=10.0,
        )
        await publisher.publish(evt)

    assert transport.get_queue_length(queue_url) == 100

    # Poll until all processed
    while transport.get_queue_length(queue_url) > 0:
        await consumer.poll_once()

    assert transport.get_queue_length(queue_url) == 0
    snapshot = metrics.get_snapshot()
    assert snapshot["sqs_messages_processed"] == 100
    assert snapshot["sqs_messages_deleted"] == 100
    assert max_active_tasks <= 5, f"Concurrency exceeded limit: {max_active_tasks} > 5"


# =====================================================================
# 7. SQS-TO-REROUTE PIPELINE INTEGRATION
# =====================================================================


def test_sqs_to_rerouting_end_to_end_pipeline(monkeypatch):
    """Full End-to-End integration test:

    SQS Message
      -> SqsEventConsumer
      -> SimulationEventHandler
      -> RuntimeRiskState (edge closed)
      -> InMemoryEventBus ("risk.edges_changed")
      -> RealtimeRerouteCoordinator
      -> A* Routing
      -> RealtimePublisher (route.recalculated emitted to frontend)
    """
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    from app.schemas.health import DependencyHealth

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
    )
    with TestClient(create_app(settings)) as client:
        # 1. Calculate route
        resp = client.post(
            "/api/v1/routes/calculate",
            json={
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            },
        )
        assert resp.status_code == 201
        route_id = resp.json()["routeId"]

        # 2. Subscribe to route via SSE publisher
        queue = client.app.state.runtime.realtime_publisher.subscribe(route_id)

        # 3. Setup SQS transport & consumer hooked to client runtime
        transport = InMemorySqsTransport()
        queue_url = "https://sqs.mock/realtime-reroute"
        metrics = MessagingMetrics()
        store = RedisIdempotencyStore(_FakeRedis())

        handler = SimulationEventHandler(runtime=client.app.state.runtime)
        registry = HandlerRegistry()
        registry.register(EVENT_SIMULATION_EMITTED, handler)

        consumer = SqsEventConsumer(
            client=transport,
            queue_url=queue_url,
            registry=registry,
            idempotency_store=store,
            metrics=metrics,
            wait_time_seconds=0,
        )

        # 4. Emit flood simulation event into SQS via SqsSimulationSink
        sqs_pub = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)
        sim_sink = SqsSimulationSink(publisher=sqs_pub)
        sim_evt = SimulationEvent(
            event_id=uuid4(),
            scenario_id="flash-sqs-test",
            sequence=1,
            event_type=EventType.FLOOD_ZONE_UPDATED,
            occurred_at=datetime.now(UTC),
            payload={
                "zone_id": "top",
                "severity": "SEVERE",
                "risk_score": 0.95,
                "confidence": 0.9,
                "target_edge_ids": ["fixture-top-1", "fixture-top-2", "fixture-top-3"],
            },
        )
        sim_sink.emit(sim_evt)
        assert transport.get_queue_length(queue_url) == 1

        # 5. Consume from SQS
        processed = asyncio.run(consumer.poll_once())
        assert processed == 1

        # 6. Verify SSE events arrived on queue
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


# =====================================================================
# 8. LATENCY BENCHMARKS
# =====================================================================


@pytest.mark.asyncio
async def test_messaging_latency_benchmarks():
    """Measures publishing and processing latency under the in-memory SQS transport."""
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/benchmark"
    metrics = MessagingMetrics()
    store = RedisIdempotencyStore(_FakeRedis())

    class _FastHandler(DomainEventHandler):
        async def handle(self, event: DomainEvent) -> None:
            pass

    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, _FastHandler())

    publisher = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)
    consumer = SqsEventConsumer(
        client=transport,
        queue_url=queue_url,
        registry=registry,
        idempotency_store=store,
        metrics=metrics,
        wait_time_seconds=0,
    )

    # 1. Measure Publish Latency
    n = 100
    events = [
        create_weather_observed_event(
            latitude=10.0,
            longitude=20.0,
            rainfall_rate_mm_h=1.0,
        )
        for i in range(n)
    ]

    t0 = time.perf_counter()
    for evt in events:
        await publisher.publish(evt)
    t1 = time.perf_counter()
    avg_publish_ms = ((t1 - t0) / n) * 1000.0

    # 2. Measure Consume & Process Latency
    t2 = time.perf_counter()
    while transport.get_queue_length(queue_url) > 0:
        await consumer.poll_once()
    t3 = time.perf_counter()
    avg_process_ms = ((t3 - t2) / n) * 1000.0

    assert avg_publish_ms < 5.0, f"Publish latency too high: {avg_publish_ms:.3f} ms"
    assert avg_process_ms < 5.0, f"Process latency too high: {avg_process_ms:.3f} ms"

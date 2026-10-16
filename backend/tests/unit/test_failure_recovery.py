import json

import pytest

from app.core.config import get_settings
from app.messaging.consumer import DomainEventHandler, HandlerRegistry
from app.messaging.errors import NonRetryableEventError, RetryableEventError
from app.messaging.idempotency import RedisIdempotencyStore
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import (
    EVENT_WEATHER_OBSERVED,
    DomainEvent,
    create_weather_observed_event,
)
from app.messaging.sqs.client import InMemorySqsTransport
from app.messaging.sqs.consumer import SqsEventConsumer
from app.messaging.sqs.publisher import SqsEventPublisher


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


class _PoisonHandler(DomainEventHandler):
    async def handle(self, event: DomainEvent) -> None:
        raise NonRetryableEventError("Poison message!")


class _TransientHandler(DomainEventHandler):
    def __init__(self, fail_until: int = 2):
        self.attempts = 0
        self.fail_until = fail_until

    async def handle(self, event: DomainEvent) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_until:
            raise RetryableEventError("Temporary failure")


@pytest.fixture
def test_settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "sqs_dlq_url", "https://sqs.mock/dlq")
    monkeypatch.setattr(settings, "sqs_retry_base_delay_seconds", 0)  # immediate retry
    monkeypatch.setattr(settings, "sqs_retry_max_delay_seconds", 0)
    monkeypatch.setattr(settings, "sqs_retry_jitter", False)
    return settings


@pytest.mark.asyncio
async def test_poison_message_quarantine(test_settings):
    """Test that NonRetryableEventError moves message to DLQ immediately."""
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/events?token=test_token_{route_id}"
    dlq_url = "https://sqs.mock/dlq"
    transport.create_queue(dlq_url)

    metrics = MessagingMetrics()
    store = RedisIdempotencyStore(_FakeRedis())

    registry = HandlerRegistry()
    registry.register(EVENT_WEATHER_OBSERVED, _PoisonHandler())

    consumer = SqsEventConsumer(
        client=transport,
        queue_url=queue_url,
        registry=registry,
        idempotency_store=store,
        metrics=metrics,
        wait_time_seconds=0,
    )

    event = create_weather_observed_event(latitude=0.0, longitude=0.0, rainfall_rate_mm_h=1.0)
    publisher = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)
    await publisher.publish(event)

    assert transport.get_queue_length(queue_url) == 1

    processed = await consumer.poll_once()
    assert processed == 0

    # Message removed from main queue
    assert transport.get_queue_length(queue_url) == 0
    # Message quarantined to DLQ
    assert transport.get_queue_length(dlq_url) == 1


@pytest.mark.asyncio
async def test_transient_failure_recovery_and_dlq(test_settings):
    """Test exponential backoff retries and max receives -> DLQ behavior."""
    transport = InMemorySqsTransport()
    queue_url = "https://sqs.mock/events?token=test_token_{route_id}"
    dlq_url = "https://sqs.mock/dlq"

    # Configure 2 max receives
    transport.configure_redrive(queue_url, dlq_url, max_receive_count=2)

    metrics = MessagingMetrics()
    store = RedisIdempotencyStore(_FakeRedis())

    # Fails 3 times, which is > max_receive_count
    handler = _TransientHandler(fail_until=3)
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

    event = create_weather_observed_event(latitude=0.0, longitude=0.0, rainfall_rate_mm_h=1.0)
    publisher = SqsEventPublisher(client=transport, queue_url=queue_url, metrics=metrics)
    await publisher.publish(event)

    # Attempt 1: fails
    processed = await consumer.poll_once()
    assert processed == 0
    assert transport.get_queue_length(queue_url) == 1
    assert handler.attempts == 1

    # Attempt 2: fails
    processed = await consumer.poll_once()
    assert processed == 0
    assert handler.attempts == 2

    # Attempt 3: moved to DLQ by InMemorySqsTransport redrive policy on receive
    processed = await consumer.poll_once()
    assert processed == 0

    assert transport.get_queue_length(queue_url) == 0
    assert transport.get_queue_length(dlq_url) == 1

"""Standalone CLI worker process running the FloodGuard SQS consumer.

Can be run independently in background or in an ECS/Fargate container:
python -m app.messaging.worker
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import from_url

from app.core.config import Settings
from app.messaging.consumer import HandlerRegistry
from app.messaging.handlers import WeatherObservedHandler
from app.messaging.idempotency import RedisIdempotencyStore
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import EVENT_WEATHER_OBSERVED
from app.messaging.serializer import EventSerializer
from app.messaging.sqs.client import Boto3SqsClient, InMemorySqsTransport
from app.messaging.sqs.consumer import SqsEventConsumer
from app.realtime.coordinator import RuntimeRiskState
from app.realtime.event_bus import InMemoryEventBus

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
)
logger = logging.getLogger("floodguard.worker")


class MessagingWorker:
    """Standalone worker hosting the SQS event consumer."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.metrics = MessagingMetrics()
        self.registry = HandlerRegistry()
        self.bus = InMemoryEventBus()
        self.risk_state = RuntimeRiskState()
        self.consumer: SqsEventConsumer | None = None
        self.redis_client: Any = None
        self.started_at: datetime | None = None

    async def start(self) -> None:
        """Initialize connections, register handlers, and start consumer loop."""
        self.started_at = datetime.now(UTC)
        logger.info("Initializing FloodGuard messaging worker...")

        # Initialize Redis for idempotency deduplication
        redis_url = self.settings.redis_url.get_secret_value()
        try:
            self.redis_client = from_url(redis_url)
            await self.redis_client.ping()
            logger.info("Connected to Redis idempotency store.")
        except Exception as err:
            logger.warning("Could not connect to Redis: %s; using degraded idempotency", err)
            self.redis_client = None

        idempotency_store = RedisIdempotencyStore(
            redis=self.redis_client,
            ttl_seconds=self.settings.sqs_idempotency_ttl_seconds,
            fallback_mode=self.settings.sqs_idempotency_fallback,
        )

        # Register domain event handlers
        weather_handler = WeatherObservedHandler(
            risk_state=self.risk_state,
            event_bus=self.bus,
        )
        self.registry.register(EVENT_WEATHER_OBSERVED, weather_handler)

        # Build SQS client
        if self.settings.sqs_endpoint_url or self.settings.sqs_enabled:
            client = Boto3SqsClient(
                region_name=self.settings.aws_region,
                endpoint_url=self.settings.sqs_endpoint_url,
            )
        else:
            client = InMemorySqsTransport()

        self.consumer = SqsEventConsumer(
            client=client,
            queue_url=self.settings.sqs_environment_queue_url,
            registry=self.registry,
            idempotency=idempotency_store,
            serializer=EventSerializer(),
            metrics=self.metrics,
            poll_wait_seconds=self.settings.sqs_poll_wait_seconds,
            max_messages=self.settings.sqs_max_messages,
            visibility_timeout=self.settings.sqs_visibility_timeout_seconds,
            concurrency=self.settings.sqs_consumer_concurrency,
        )

        self.consumer.start()
        logger.info("FloodGuard messaging worker successfully started.")

    async def stop(self) -> None:
        """Clean shutdown."""
        logger.info("Shutting down messaging worker...")
        if self.consumer:
            await self.consumer.stop()
        if self.redis_client:
            await self.redis_client.aclose()
        logger.info("Messaging worker stopped.")

    def get_health(self) -> dict[str, Any]:
        """Simple health state report for worker monitoring."""
        return {
            "status": "RUNNING" if self.consumer and self.consumer.is_running else "STOPPED",
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_poll_at": (
                self.consumer.last_poll_at.isoformat()
                if self.consumer and self.consumer.last_poll_at
                else None
            ),
            "last_processed_at": (
                self.consumer.last_processed_at.isoformat()
                if self.consumer and self.consumer.last_processed_at
                else None
            ),
            "metrics": self.metrics.snapshot(),
        }


async def main() -> None:
    settings = Settings()
    worker = MessagingWorker(settings)
    await worker.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        await worker.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)

"""AWS SQS implementation of EventPublisher."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.messaging.envelope import TransportEnvelope
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import DomainEvent
from app.messaging.publisher import EventPublisher, PublishResult
from app.messaging.serializer import EventSerializer
from app.messaging.sqs.client import SqsClientInterface

logger = logging.getLogger("floodguard.messaging.sqs.publisher")


class SqsEventPublisher(EventPublisher):
    """Publishes domain events to an AWS SQS queue wrapped in canonical envelopes."""

    def __init__(
        self,
        client: SqsClientInterface,
        queue_url: str,
        serializer: EventSerializer | None = None,
        metrics: MessagingMetrics | None = None,
    ) -> None:
        self.client = client
        self.queue_url = queue_url
        self.serializer = serializer or EventSerializer()
        self.metrics = metrics or MessagingMetrics()

    async def publish(self, event: DomainEvent) -> PublishResult:
        """Publish a domain event to the SQS queue."""
        t0 = time.perf_counter()
        envelope = TransportEnvelope.from_domain(event)

        try:
            body = self.serializer.serialize(envelope)
        except Exception as err:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.metrics.record_publish_error()
            logger.error(
                "Serialization failed for domain event %s: %s",
                event.event_id,
                err,
                extra={"event_id": event.event_id, "event_type": event.event_type},
            )
            return PublishResult(
                success=False,
                event_id=event.event_id,
                queue_url=self.queue_url,
                error=f"Serialization failure: {err}",
                latency_ms=round(elapsed_ms, 3),
            )

        # Message attributes for queue filtering and traceability
        msg_attributes: dict[str, Any] = {
            "event_type": {
                "DataType": "String",
                "StringValue": event.event_type,
            },
            "event_version": {
                "DataType": "Number",
                "StringValue": str(event.event_version),
            },
            "correlation_id": {
                "DataType": "String",
                "StringValue": event.correlation_id,
            },
        }
        if event.causation_id:
            msg_attributes["causation_id"] = {
                "DataType": "String",
                "StringValue": event.causation_id,
            }

        try:
            resp = await self.client.send_message(
                queue_url=self.queue_url,
                message_body=body,
                message_attributes=msg_attributes,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            msg_id = resp.get("MessageId")

            self.metrics.record_published(elapsed_ms)
            logger.info(
                "sqs_message_published",
                extra={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "event_version": event.event_version,
                    "correlation_id": event.correlation_id,
                    "message_id": msg_id,
                    "latency_ms": round(elapsed_ms, 3),
                    "queue_url": self.queue_url,
                },
            )
            return PublishResult(
                success=True,
                event_id=event.event_id,
                message_id=msg_id,
                queue_url=self.queue_url,
                latency_ms=round(elapsed_ms, 3),
            )

        except Exception as err:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            self.metrics.record_publish_error()
            logger.error(
                "Failed to publish SQS message for event %s: %s",
                event.event_id,
                err,
                extra={
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "correlation_id": event.correlation_id,
                    "queue_url": self.queue_url,
                },
            )
            return PublishResult(
                success=False,
                event_id=event.event_id,
                queue_url=self.queue_url,
                error=str(err),
                latency_ms=round(elapsed_ms, 3),
            )

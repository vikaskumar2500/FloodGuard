"""Canonical domain envelopes published with item-level EventBridge acceptance results."""

import logging
import time
from typing import Any

from app.messaging.envelope import TransportEnvelope
from app.messaging.eventbridge.client import EventBridgeClient
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import DomainEvent
from app.messaging.publisher import EventPublisher, PublishResult
from app.messaging.serializer import EventSerializer

logger = logging.getLogger("floodguard.messaging.eventbridge.publisher")
MAX_ENTRIES = 10
# AWS aggregate entry size must be strictly below 1 MiB. See docs/eventbridge.md.
MAX_REQUEST_BYTES = 1_048_576


def entry_size(entry: dict[str, Any]) -> int:
    return sum(len(entry[key].encode("utf-8")) for key in ("Source", "DetailType", "Detail"))


class EventBridgeEventPublisher(EventPublisher):
    def __init__(
        self,
        client: EventBridgeClient,
        bus_name: str,
        source: str = "com.floodguard",
        metrics: MessagingMetrics | None = None,
    ) -> None:
        if not bus_name.strip() or bus_name == "default" or bus_name.endswith(":event-bus/default"):
            raise ValueError("A custom EventBridge bus name or ARN is required")
        if not source.strip():
            raise ValueError("EventBridge source is required")
        self.client = client
        self.bus_name = bus_name
        self.source = source
        self.metrics = metrics or MessagingMetrics()

    async def publish(self, event: DomainEvent) -> PublishResult:
        return (await self.publish_batch([event]))[0]

    async def publish_batch(self, events: list[DomainEvent]) -> list[PublishResult]:
        results: dict[int, PublishResult] = {}
        batch: list[tuple[int, DomainEvent, dict[str, Any]]] = []
        size = 0
        for index, event in enumerate(events):
            self.metrics.increment("eventbridge_publish_total")
            try:
                entry = {
                    "Source": self.source,
                    "DetailType": event.event_type,
                    "Detail": EventSerializer.serialize(TransportEnvelope.from_domain(event)),
                    "EventBusName": self.bus_name,
                }
                event_size = entry_size(entry)
            except Exception:
                results[index] = self._result(event, error_code="SerializationError")
                continue
            if event_size >= MAX_REQUEST_BYTES:
                self.metrics.increment("eventbridge_oversized_total")
                results[index] = self._result(event, error_code="EventTooLarge")
                continue
            if batch and (len(batch) == MAX_ENTRIES or size + event_size >= MAX_REQUEST_BYTES):
                results.update(await self._send(batch))
                batch, size = [], 0
            batch.append((index, event, entry))
            size += event_size
        if batch:
            results.update(await self._send(batch))
        return [results[i] for i in range(len(events))]

    async def _send(self, batch: list[tuple[int, DomainEvent, dict]]) -> dict[int, PublishResult]:
        start = time.perf_counter()
        try:
            response = await self.client.put_events(Entries=[entry for _, _, entry in batch])
            entries = response.get("Entries", [])
            # Do not invent successful results for incomplete/inconsistent API responses.
            valid = (
                len(entries) == len(batch)
                and all(isinstance(item, dict) for item in entries)
                and response.get("FailedEntryCount")
                == sum(bool(item.get("ErrorCode") or not item.get("EventId")) for item in entries)
            )
            if not valid:
                raise ValueError("Invalid PutEvents response")
        except Exception as error:
            code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
            return {
                i: self._result(event, error_code=code, failed_count=len(batch), start=start)
                for i, event, _ in batch
            }
        failed = response["FailedEntryCount"]
        if 0 < failed < len(batch):
            self.metrics.increment("eventbridge_partial_failure_total")
        return {
            index: self._result(
                event,
                eventbridge_id=item.get("EventId") if not item.get("ErrorCode") else None,
                error_code=item.get("ErrorCode"),
                failed_count=failed,
                start=start,
            )
            for (index, event, _), item in zip(batch, entries, strict=True)
        }

    def _result(
        self,
        event: DomainEvent,
        *,
        eventbridge_id: str | None = None,
        error_code: str | None = None,
        failed_count: int = 1,
        start: float | None = None,
    ) -> PublishResult:
        success = bool(eventbridge_id) and error_code is None
        self.metrics.increment(
            "eventbridge_publish_success_total" if success else "eventbridge_publish_failure_total"
        )
        logger.info(
            "eventbridge_publish",
            extra={
                "domain_event_id": event.event_id,
                "eventbridge_event_id": eventbridge_id,
                "event_type": event.event_type,
                "correlation_id": event.correlation_id,
                "bus_name": self.bus_name,
                "source": self.source,
                "publish_status": "accepted" if success else "failed",
                "error_code": error_code,
            },
        )
        return PublishResult(
            success=success,
            event_id=event.event_id,
            eventbridge_event_id=eventbridge_id,
            failed_entry_count=failed_count,
            error_code=error_code,
            error=error_code,
            latency_ms=(time.perf_counter() - start) * 1000 if start else 0.0,
        )

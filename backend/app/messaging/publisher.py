"""Transport-neutral EventPublisher abstraction and InMemory implementation."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.messaging.models import DomainEvent


@dataclass(frozen=True)
class PublishResult:
    """Result of attempting to publish a domain event to a queue or broker."""

    success: bool
    event_id: str
    message_id: str | None = None
    queue_url: str | None = None
    error: str | None = None
    latency_ms: float = 0.0
    eventbridge_event_id: str | None = None
    failed_entry_count: int = 0
    error_code: str | None = None


class EventPublisher(ABC):
    """Abstract publisher interface for domain events."""

    @abstractmethod
    async def publish(self, event: DomainEvent) -> PublishResult:
        """Publish a single domain event asynchronously."""

    async def publish_batch(self, events: list[DomainEvent]) -> list[PublishResult]:
        """Publish a batch of domain events."""
        results: list[PublishResult] = []
        for event in events:
            res = await self.publish(event)
            results.append(res)
        return results


class InMemoryEventPublisher(EventPublisher):
    """In-memory event publisher for local testing and IN_PROCESS mode."""

    def __init__(self) -> None:
        self.published_events: list[DomainEvent] = []
        self._handlers: list[Any] = []
        self._fail_next: bool = False

    def simulate_failure(self, fail: bool = True) -> None:
        """Testing hook to simulate network or transport outage."""
        self._fail_next = fail

    async def publish(self, event: DomainEvent) -> PublishResult:
        t0 = time.perf_counter()
        if self._fail_next:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return PublishResult(
                success=False,
                event_id=event.event_id,
                error="Simulated publisher connection failure",
                latency_ms=round(elapsed_ms, 3),
            )

        self.published_events.append(event)
        for h in self._handlers:
            try:
                await h(event)
            except Exception:
                pass

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return PublishResult(
            success=True,
            event_id=event.event_id,
            message_id=f"inmem-{len(self.published_events)}",
            queue_url="in-memory://events",
            latency_ms=round(elapsed_ms, 3),
        )

    def subscribe(self, callback: Any) -> None:
        """Register listener for published events."""
        self._handlers.append(callback)

    def clear(self) -> None:
        self.published_events.clear()
        self._fail_next = False

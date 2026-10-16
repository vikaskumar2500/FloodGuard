"""Domain event handler interface and registry."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.messaging.models import DomainEvent

logger = logging.getLogger("floodguard.messaging.consumer")


class DomainEventHandler(ABC):
    """Abstract interface for domain event handlers."""

    @abstractmethod
    async def handle(self, event: DomainEvent) -> None:
        """Process domain event.

        Must raise an exception on transient failure to trigger SQS redelivery.
        Must NOT catch and swallow exceptions that indicate failed side effects.
        """


class HandlerRegistry:
    """Registry mapping public eventType strings to their domain event handlers."""

    def __init__(self) -> None:
        self._handlers: dict[str, DomainEventHandler] = {}

    def register(self, event_type: str, handler: DomainEventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type] = handler
        logger.debug("Registered handler for event type: %s", event_type)

    def get(self, event_type: str) -> DomainEventHandler | None:
        """Retrieve handler for event type, or None if unknown."""
        return self._handlers.get(event_type)

    @property
    def registered_types(self) -> list[str]:
        return list(self._handlers.keys())

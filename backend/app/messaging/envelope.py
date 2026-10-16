"""Canonical Transport Envelope for FloodGuard asynchronous messaging.

Enforces a standard envelope across all transports (SQS, in-memory, or future brokers).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.messaging.models import DomainEvent


@dataclass(frozen=True)
class TransportEnvelope:
    """Canonical transport envelope carrying domain event metadata and payload."""

    event_id: str
    event_type: str
    event_version: int
    occurred_at: datetime
    producer: str
    correlation_id: str
    causation_id: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert envelope to serializable dictionary format."""
        return {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "eventVersion": self.event_version,
            "occurredAt": (
                self.occurred_at.astimezone(UTC).isoformat()
                if self.occurred_at.tzinfo
                else self.occurred_at.replace(tzinfo=UTC).isoformat()
            ),
            "producer": self.producer,
            "correlationId": self.correlation_id,
            "causationId": self.causation_id,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransportEnvelope:
        """Construct envelope from parsed dictionary."""
        occurred_raw = data.get("occurredAt")
        if not occurred_raw:
            raise ValueError("Missing 'occurredAt' in envelope")

        try:
            occurred_at = datetime.fromisoformat(str(occurred_raw))
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
        except Exception as err:
            raise ValueError(f"Invalid 'occurredAt' timestamp: {occurred_raw}") from err

        return cls(
            event_id=str(data["eventId"]),
            event_type=str(data["eventType"]),
            event_version=int(data.get("eventVersion", 1)),
            occurred_at=occurred_at,
            producer=str(data.get("producer", "unknown")),
            correlation_id=str(data.get("correlationId", "")),
            causation_id=str(data["causationId"]) if data.get("causationId") else None,
            payload=dict(data.get("payload", {})),
        )

    @classmethod
    def from_domain(cls, event: DomainEvent) -> TransportEnvelope:
        """Wrap domain event into canonical transport envelope."""
        return cls(
            event_id=event.event_id,
            event_type=event.event_type,
            event_version=event.event_version,
            occurred_at=event.occurred_at,
            producer=event.producer,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
        )

    from_domain_event = from_domain

    def to_domain(self) -> DomainEvent:
        """Extract domain event from transport envelope."""
        return DomainEvent(
            event_id=self.event_id,
            event_type=self.event_type,
            event_version=self.event_version,
            occurred_at=self.occurred_at,
            producer=self.producer,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            payload=self.payload,
        )

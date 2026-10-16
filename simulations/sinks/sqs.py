"""Shared simulation adapter for SQS and EventBridge EventPublisher implementations."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from simulations.models import SimulationEvent


class SqsSimulationSink:
    """Publishes simulation events to an SQS queue via an EventPublisher or SQS transport."""

    def __init__(
        self,
        publisher: Any,
        producer_id: str = "simulation.engine",
    ) -> None:
        self.publisher = publisher
        self.producer_id = producer_id
        self.events_emitted = 0

    def emit(self, event: SimulationEvent) -> None:
        """Synchronously emit event by running publisher in event loop or task."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(self.emit_async(event))
            return
        raise RuntimeError("Use await sink.emit_async(event) inside an event loop")

    async def emit_async(self, event: SimulationEvent) -> None:
        """Asynchronously emit event to publisher."""
        from app.messaging.models import create_simulation_emitted_event

        domain_event = create_simulation_emitted_event(
            simulation_event_id=str(event.event_id),
            scenario_id=event.scenario_id,
            sim_event_type=event.event_type.value,
            sim_payload=event.payload,
            occurred_at=event.occurred_at,
            producer=self.producer_id,
            correlation_id=str(uuid4()),
            sequence=getattr(event, "sequence", 1),
        )
        result = await self.publisher.publish(domain_event)
        if not result.success:
            raise RuntimeError(f"Simulation publication failed: {result.error}")
        self.events_emitted += 1

    def close(self) -> None:
        return None

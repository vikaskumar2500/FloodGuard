"""Domain event handlers connecting SQS events to FloodGuard's risk and routing pipelines."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app.messaging.consumer import DomainEventHandler
from app.messaging.models import DomainEvent
from app.realtime.coordinator import RuntimeRiskState
from app.realtime.event_bus import InMemoryEventBus
from app.realtime.simulation_models import SimulationEvent, SimulationEventType

logger = logging.getLogger("floodguard.messaging.handlers")


class WeatherObservedHandler(DomainEventHandler):
    """Processes normalized weather observations from SQS and updates RuntimeRiskState.

    Enforces CRITICAL INVARIANT 5:
    Out-of-order events must not regress environmental state.
    """

    def __init__(
        self,
        risk_state: RuntimeRiskState,
        event_bus: InMemoryEventBus,
        default_edges: list[str] | None = None,
    ) -> None:
        self.risk_state = risk_state
        self.event_bus = event_bus
        self.default_edges = default_edges or []
        self._latest_occurred_per_edge: dict[str, datetime] = {}

    async def handle(self, event: DomainEvent) -> None:
        payload = event.payload
        rain_rate = payload.get("rainfallRateMmPerHour")
        target_edges = payload.get("roadEdgeIds") or self.default_edges
        if not target_edges:
            logger.info("Weather observation has no target edges; skipping risk update.")
            return

        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)

        changes: dict[str, tuple[float, str, bool]] = {}
        for edge_id in target_edges:
            latest = self._latest_occurred_per_edge.get(edge_id)
            if latest is not None and occurred_at < latest:
                logger.info(
                    "stale_weather_event_ignored",
                    extra={
                        "event_id": event.event_id,
                        "edge_id": edge_id,
                        "event_occurred_at": occurred_at.isoformat(),
                        "latest_occurred_at": latest.isoformat(),
                    },
                )
                continue

            self._latest_occurred_per_edge[edge_id] = occurred_at

            # Calculate deterministic risk score based on rainfall rate
            if rain_rate is None or rain_rate < 5.0:
                score, level, closed = 0.1, "LOW", False
            elif rain_rate < 15.0:
                score, level, closed = 0.4, "MODERATE", False
            elif rain_rate < 30.0:
                score, level, closed = 0.75, "HIGH", False
            else:
                score, level, closed = 0.95, "SEVERE", True

            changes[str(edge_id)] = (score, level, closed)

        if not changes:
            return

        revision, material = self.risk_state.apply(event.event_id, changes)
        logger.info(
            "weather_observation_applied",
            extra={
                "event_id": event.event_id,
                "correlation_id": event.correlation_id,
                "risk_revision": revision,
                "material_changes": len(material),
            },
        )

        if material:
            # Emit internal risk.edges_changed event over in-process event bus
            await self.event_bus.publish_async(
                {
                    "eventType": "risk.edges_changed",
                    "riskRevision": revision,
                    "edgeIds": sorted(material),
                    "sourceEventId": event.event_id,
                    "correlationId": event.correlation_id,
                    "causationId": event.event_id,
                }
            )


class SensorObservationHandler(DomainEventHandler):
    """Processes sensor water depth readings from SQS and updates RuntimeRiskState."""

    def __init__(
        self,
        risk_state: RuntimeRiskState,
        event_bus: InMemoryEventBus,
    ) -> None:
        self.risk_state = risk_state
        self.event_bus = event_bus
        self._latest_occurred_per_edge: dict[str, datetime] = {}

    async def handle(self, event: DomainEvent) -> None:
        payload = event.payload
        edge_id = str(payload["roadEdgeId"])
        water_depth = payload.get("waterDepthCm")

        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)

        latest = self._latest_occurred_per_edge.get(edge_id)
        if latest is not None and occurred_at < latest:
            logger.info(
                "stale_sensor_event_ignored",
                extra={
                    "event_id": event.event_id,
                    "edge_id": edge_id,
                    "event_occurred_at": occurred_at.isoformat(),
                    "latest_occurred_at": latest.isoformat(),
                },
            )
            return

        self._latest_occurred_per_edge[edge_id] = occurred_at

        # Risk mapping from water depth
        if water_depth is None or water_depth < 5.0:
            score, level, closed = 0.1, "LOW", False
        elif water_depth < 15.0:
            score, level, closed = 0.45, "MODERATE", False
        elif water_depth < 30.0:
            score, level, closed = 0.80, "HIGH", True
        else:
            score, level, closed = 1.00, "SEVERE", True

        changes = {edge_id: (score, level, closed)}
        revision, material = self.risk_state.apply(event.event_id, changes)

        if material:
            await self.event_bus.publish_async(
                {
                    "eventType": "risk.edges_changed",
                    "riskRevision": revision,
                    "edgeIds": sorted(material),
                    "sourceEventId": event.event_id,
                    "correlationId": event.correlation_id,
                    "causationId": event.event_id,
                }
            )


class SimulationEventHandler(DomainEventHandler):
    """Processes simulator events arriving through SQS and feeds them to FloodGuardRuntime."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._latest_occurred_at: datetime | None = None

    async def handle(self, event: DomainEvent) -> None:
        payload = event.payload
        sim_data = payload.get("data", {})
        sim_type_str = payload.get("simEventType")

        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)

        if self._latest_occurred_at is not None and occurred_at < self._latest_occurred_at:
            logger.info(
                "stale_simulation_event_ignored",
                extra={
                    "event_id": event.event_id,
                    "occurred_at": occurred_at.isoformat(),
                    "latest_at": self._latest_occurred_at.isoformat(),
                },
            )
            return

        self._latest_occurred_at = occurred_at

        try:
            event_type_enum = SimulationEventType(sim_type_str)
        except Exception:
            event_type_enum = SimulationEventType.FLOOD_ZONE_UPDATED

        try:
            eid = UUID(str(event.event_id))
        except Exception:
            eid = uuid4()

        sim_event = SimulationEvent(
            event_id=eid,
            scenario_id=str(payload.get("scenarioId", "sqs-scenario")),
            event_type=event_type_enum,
            occurred_at=occurred_at,
            sequence=int(payload.get("sequence", 1)),
            payload=sim_data,
        )

        res = await self.runtime.apply_simulation(sim_event)
        logger.info(
            "sqs_simulation_event_applied_to_runtime",
            extra={
                "event_id": event.event_id,
                "correlation_id": event.correlation_id,
                "risk_revision": res.get("riskRevision"),
                "material_change": res.get("materialChange"),
            },
        )

"""Domain event models for FloodGuard asynchronous messaging (Phase 14).

All domain models remain transport-independent. SQS or other transports wrap
these events in a TransportEnvelope without altering domain semantics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

# Canonical Event Type Constants (Stable public naming)
EVENT_WEATHER_OBSERVED = "environment.weather_observed"
EVENT_SENSOR_WATER_DEPTH = "sensor.water_depth_observed"
EVENT_SENSOR_HEALTH = "sensor.health_changed"
EVENT_FLOOD_ZONE_UPDATED = "flood.zone_updated"
EVENT_INCIDENT_REPORTED = "incident.reported"
EVENT_SIMULATION_EMITTED = "simulation.event_emitted"
EVENT_RISK_EDGES_CHANGED = "risk.edges_changed"


@dataclass(frozen=True)
class DomainEvent:
    """Base transport-neutral domain event."""

    event_id: str
    event_type: str
    occurred_at: datetime
    producer: str
    correlation_id: str
    event_version: int = 1
    causation_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def create_weather_observed_event(
    latitude: float,
    longitude: float,
    rainfall_rate_mm_h: float | None,
    rainfall_accum_1h_mm: float | None = None,
    temperature_c: float | None = None,
    observation_time: datetime | None = None,
    road_edge_ids: list[str] | None = None,
    producer: str = "environment.weather_provider",
    correlation_id: str | None = None,
    causation_id: str | None = None,
    event_id: str | None = None,
) -> DomainEvent:
    """Construct a normalized weather observation domain event."""
    now = observation_time or datetime.now(UTC)
    c_id = correlation_id or str(uuid4())
    e_id = event_id or str(uuid4())
    payload = {
        "latitude": latitude,
        "longitude": longitude,
        "rainfallRateMmPerHour": rainfall_rate_mm_h,
        "rainfallAccum1hMm": rainfall_accum_1h_mm,
        "temperatureC": temperature_c,
        "observationTime": now.isoformat(),
        "roadEdgeIds": road_edge_ids or [],
    }
    return DomainEvent(
        event_id=e_id,
        event_type=EVENT_WEATHER_OBSERVED,
        event_version=1,
        occurred_at=now,
        producer=producer,
        correlation_id=c_id,
        causation_id=causation_id,
        payload=payload,
    )


def create_sensor_water_depth_event(
    sensor_id: str,
    road_edge_id: str,
    water_depth_cm: float | None,
    rainfall_mm_h: float | None = None,
    quality: str = "GOOD",
    observed_at: datetime | None = None,
    producer: str = "sensors.ingestion",
    correlation_id: str | None = None,
    causation_id: str | None = None,
    event_id: str | None = None,
) -> DomainEvent:
    """Construct a sensor water depth observation domain event."""
    now = observed_at or datetime.now(UTC)
    c_id = correlation_id or str(uuid4())
    e_id = event_id or str(uuid4())
    payload = {
        "sensorId": sensor_id,
        "roadEdgeId": road_edge_id,
        "waterDepthCm": water_depth_cm,
        "rainfallMmPerHour": rainfall_mm_h,
        "quality": quality,
        "observedAt": now.isoformat(),
    }
    return DomainEvent(
        event_id=e_id,
        event_type=EVENT_SENSOR_WATER_DEPTH,
        event_version=1,
        occurred_at=now,
        producer=producer,
        correlation_id=c_id,
        causation_id=causation_id,
        payload=payload,
    )


def create_simulation_emitted_event(
    simulation_event_id: str,
    scenario_id: str,
    sim_event_type: str,
    sim_payload: dict[str, Any],
    occurred_at: datetime | None = None,
    producer: str = "simulator.engine",
    correlation_id: str | None = None,
    causation_id: str | None = None,
    sequence: int = 1,
) -> DomainEvent:
    """Construct a simulation emitted domain event for SQS replay."""
    now = occurred_at or datetime.now(UTC)
    c_id = correlation_id or str(uuid4())
    payload = {
        "simulationEventId": simulation_event_id,
        "scenarioId": scenario_id,
        "simEventType": sim_event_type,
        "sequence": sequence,
        "data": sim_payload,
    }
    return DomainEvent(
        event_id=simulation_event_id,
        event_type=EVENT_SIMULATION_EMITTED,
        event_version=1,
        occurred_at=now,
        producer=producer,
        correlation_id=c_id,
        causation_id=causation_id,
        payload=payload,
    )


def create_risk_edges_changed_event(
    risk_revision: int,
    edge_ids: list[str],
    source_event_id: str,
    occurred_at: datetime | None = None,
    producer: str = "floodguard.runtime_risk_state",
    correlation_id: str | None = None,
) -> DomainEvent:
    """Construct a risk.edges_changed domain event."""
    now = occurred_at or datetime.now(UTC)
    c_id = correlation_id or str(uuid4())
    e_id = str(uuid4())
    payload = {
        "riskRevision": risk_revision,
        "edgeIds": edge_ids,
        "sourceEventId": source_event_id,
    }
    return DomainEvent(
        event_id=e_id,
        event_type=EVENT_RISK_EDGES_CHANGED,
        event_version=1,
        occurred_at=now,
        producer=producer,
        correlation_id=c_id,
        causation_id=source_event_id,
        payload=payload,
    )

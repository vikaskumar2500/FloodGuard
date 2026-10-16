from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from math import isfinite
from typing import Any
from uuid import UUID, uuid5

SIMULATION_NAMESPACE = UUID("b8f3d5c9-7f8b-4f5d-9ec5-d31c19a1b2ee")


class EventType(StrEnum):
    RAINFALL_OBSERVATION = "RAINFALL_OBSERVATION"
    WATER_DEPTH_READING = "WATER_DEPTH_READING"
    FLOOD_ZONE_ACTIVATED = "FLOOD_ZONE_ACTIVATED"
    FLOOD_ZONE_UPDATED = "FLOOD_ZONE_UPDATED"
    FLOOD_ZONE_CLEARED = "FLOOD_ZONE_CLEARED"
    INCIDENT_REPORTED = "INCIDENT_REPORTED"
    INCIDENT_RESOLVED = "INCIDENT_RESOLVED"
    SENSOR_HEALTH_CHANGED = "SENSOR_HEALTH_CHANGED"
    SENSOR_READING = "SENSOR_READING"
    WEATHER_OBSERVATION = "WEATHER_OBSERVATION"


class SensorType(StrEnum):
    RAIN_GAUGE = "RAIN_GAUGE"
    WATER_LEVEL = "WATER_LEVEL"
    WEATHER_STATION = "WEATHER_STATION"


class SensorStatus(StrEnum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


@dataclass(frozen=True)
class SensorDefinition:
    sensor_id: str
    sensor_type: SensorType
    longitude: float
    latitude: float


@dataclass(frozen=True)
class ScenarioStep:
    offset: timedelta
    event_type: EventType
    payload: dict[str, Any]


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    description: str
    duration: timedelta
    steps: tuple[ScenarioStep, ...]
    sensors: tuple[SensorDefinition, ...] = ()


@dataclass(frozen=True)
class SimulationEvent:
    event_id: UUID
    scenario_id: str
    sequence: int
    event_type: EventType
    occurred_at: datetime
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        scenario_id: str,
        sequence: int,
        event_type: EventType,
        occurred_at: datetime,
        payload: dict[str, Any],
    ) -> "SimulationEvent":
        return cls(
            event_id=uuid5(SIMULATION_NAMESPACE, f"{scenario_id}:{sequence}"),
            scenario_id=scenario_id,
            sequence=sequence,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "scenario_id": self.scenario_id,
            "sequence": self.sequence,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at.isoformat(),
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SimulationEvent":
        return cls(
            event_id=UUID(str(value["event_id"])),
            scenario_id=str(value["scenario_id"]),
            sequence=int(value["sequence"]),
            event_type=EventType(str(value["event_type"])),
            occurred_at=datetime.fromisoformat(str(value["occurred_at"])),
            payload=dict(value["payload"]),
        )


def validate_coordinate(longitude: float, latitude: float) -> None:
    if not (
        isfinite(longitude)
        and isfinite(latitude)
        and -180 <= longitude <= 180
        and -90 <= latitude <= 90
    ):
        raise ValueError("simulation coordinates must be finite WGS84 values")


def validate_event(event: SimulationEvent, start_time: datetime, duration: timedelta) -> None:
    if event.occurred_at.tzinfo is None or start_time.tzinfo is None:
        raise ValueError("simulation timestamps must be timezone-aware")
    if event.occurred_at < start_time or event.occurred_at > start_time + duration:
        raise ValueError("simulation event is outside scenario duration")
    payload = event.payload
    if "longitude" in payload or "latitude" in payload:
        validate_coordinate(float(payload.get("longitude")), float(payload.get("latitude")))
    for key in ("rainfall_mm_per_hour", "water_depth_cm"):
        if key in payload:
            value = float(payload[key])
            if not isfinite(value) or value < 0:
                raise ValueError(f"{key} must be finite and nonnegative")
    if "unit" in payload and payload["unit"] not in {"mm/hour", "cm"}:
        raise ValueError("simulation measurement unit is unsupported")

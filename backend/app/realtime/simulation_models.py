from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class SimulationEventType(StrEnum):
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


class SimulationEvent(BaseModel):
    event_id: UUID
    scenario_id: str
    sequence: int
    event_type: SimulationEventType
    occurred_at: datetime
    payload: dict[str, Any]

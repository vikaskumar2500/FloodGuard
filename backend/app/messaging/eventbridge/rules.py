"""Versioned routing contracts shared by local tests and infrastructure provisioning."""

from app.messaging.models import (
    EVENT_INCIDENT_REPORTED,
    EVENT_SENSOR_HEALTH,
    EVENT_SENSOR_WATER_DEPTH,
    EVENT_SIMULATION_EMITTED,
    EVENT_WEATHER_OBSERVED,
)

RULE_EVENT_TYPES = {
    "environment-events": [EVENT_WEATHER_OBSERVED],
    "sensor-events": [EVENT_SENSOR_WATER_DEPTH, EVENT_SENSOR_HEALTH],
    "simulation-events": [EVENT_SIMULATION_EMITTED],
}
# Contract only: no incident target until an incident handler exists (Phase 19).
INCIDENT_EVENT_PATTERN = {"detail-type": [EVENT_INCIDENT_REPORTED]}


def processing_rules(source: str = "com.floodguard") -> dict[str, dict]:
    return {
        f"floodguard-v1-{name}": {
            "source": [source],
            "detail-type": types,
            "detail": {"eventVersion": [1]},
        }
        for name, types in RULE_EVENT_TYPES.items()
    }

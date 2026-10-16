from datetime import timedelta
from random import Random

from simulations.models import (
    EventType,
    ScenarioDefinition,
    ScenarioStep,
    SensorDefinition,
    SensorStatus,
    SensorType,
)

SENSOR = SensorDefinition("sim-water-1", SensorType.WATER_LEVEL, 72.8775, 19.076)
RAIN_GAUGE = SensorDefinition("sim-rain-1", SensorType.RAIN_GAUGE, 72.8777, 19.076)


def _rainfall(offset: int, value: float, sensor: SensorDefinition = RAIN_GAUGE) -> ScenarioStep:
    return ScenarioStep(
        timedelta(minutes=offset),
        EventType.RAINFALL_OBSERVATION,
        {
            "producer": "floodguard-simulator",
            "external_event_id": f"rain-{offset}",
            "sensor_id": sensor.sensor_id,
            "longitude": sensor.longitude,
            "latitude": sensor.latitude,
            "rainfall_mm_per_hour": value,
            "unit": "mm/hour",
            "quality": "SIMULATED",
        },
    )


def _water(offset: int, value: float, sensor: SensorDefinition = SENSOR) -> ScenarioStep:
    return ScenarioStep(
        timedelta(minutes=offset),
        EventType.WATER_DEPTH_READING,
        {
            "producer": "floodguard-simulator",
            "external_event_id": f"water-{offset}",
            "sensor_id": sensor.sensor_id,
            "longitude": sensor.longitude,
            "latitude": sensor.latitude,
            "water_depth_cm": value,
            "unit": "cm",
            "quality": "SIMULATED",
            "target_edge_ids": ["fixture-top-1", "fixture-top-2", "fixture-top-3"],
        },
    )


def _health(offset: int, status: SensorStatus, sensor: SensorDefinition = SENSOR) -> ScenarioStep:
    return ScenarioStep(
        timedelta(minutes=offset),
        EventType.SENSOR_HEALTH_CHANGED,
        {
            "sensor_id": sensor.sensor_id,
            "status": status.value,
            "target_edge_ids": ["fixture-top-1", "fixture-top-2", "fixture-top-3"],
        },
    )


def _zone(offset: int, event_type: EventType, severity: str, score: float) -> ScenarioStep:
    return ScenarioStep(
        timedelta(minutes=offset),
        event_type,
        {
            "zone_id": "sim-zone-top-corridor",
            "severity": severity,
            "risk_score": score,
            "confidence": 0.9,
            "target_edge_ids": ["fixture-top-1", "fixture-top-2", "fixture-top-3"],
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [72.877, 19.0758],
                        [72.879, 19.0758],
                        [72.879, 19.0763],
                        [72.877, 19.0763],
                        [72.877, 19.0758],
                    ]
                ],
            },
        },
    )


def _incident(
    offset: int,
    event_type: EventType = EventType.INCIDENT_REPORTED,
    status: str = "REPORTED",
) -> ScenarioStep:
    return ScenarioStep(
        timedelta(minutes=offset),
        event_type,
        {
            "incident_id": "sim-incident-top-waterlogging",
            "incident_type": "WATERLOGGING",
            "severity": "HIGH",
            "status": status,
            "confidence": 0.8,
            "longitude": 72.878,
            "latitude": 19.076,
            "target_edge_ids": ["fixture-top-2"],
        },
    )


def _definition(name: str, rng: Random) -> ScenarioDefinition:
    variation = rng.randint(0, 2)
    if name == "NORMAL":
        return ScenarioDefinition(
            name,
            "Healthy sensors and near-zero environmental conditions.",
            timedelta(minutes=15),
            (_rainfall(0, 0), _water(0, 0), _health(0, SensorStatus.ONLINE)),
            (SENSOR, RAIN_GAUGE),
        )
    if name == "MODERATE_RAIN":
        return ScenarioDefinition(
            name,
            "Moderate rainfall with limited accumulation.",
            timedelta(minutes=25),
            (
                _health(0, SensorStatus.ONLINE),
                _rainfall(0, 8 + variation),
                _rainfall(10, 15 + variation),
                _water(10, 8 + variation),
                _water(20, 12 + variation),
            ),
            (SENSOR, RAIN_GAUGE),
        )
    if name == "SEVERE_RAIN":
        return ScenarioDefinition(
            name,
            "Heavy rainfall and substantial water accumulation.",
            timedelta(minutes=30),
            (
                _health(0, SensorStatus.ONLINE),
                _rainfall(0, 25 + variation),
                _rainfall(10, 42 + variation),
                _water(10, 18 + variation),
                _water(20, 34 + variation),
                _zone(25, EventType.FLOOD_ZONE_ACTIVATED, "HIGH", 0.78),
            ),
            (SENSOR, RAIN_GAUGE),
        )
    if name == "FLASH_FLOOD":
        return ScenarioDefinition(
            name,
            "Staged rainfall, flash flooding, incident, and corridor impact.",
            timedelta(minutes=30),
            (
                _health(0, SensorStatus.ONLINE),
                _rainfall(0, 0),
                _rainfall(5, 35 + variation),
                _water(10, 12 + variation),
                _zone(15, EventType.FLOOD_ZONE_ACTIVATED, "HIGH", 0.78),
                _water(20, 31 + variation),
                _zone(20, EventType.FLOOD_ZONE_UPDATED, "SEVERE", 0.95),
                _incident(25),
            ),
            (SENSOR, RAIN_GAUGE),
        )
    if name == "SENSOR_OUTAGE":
        return ScenarioDefinition(
            name,
            "Healthy readings followed by degraded and offline sensors.",
            timedelta(minutes=25),
            (
                _health(0, SensorStatus.ONLINE),
                _water(0, 4),
                _rainfall(0, 12),
                _health(10, SensorStatus.DEGRADED),
                _health(15, SensorStatus.OFFLINE),
                _rainfall(20, 30),
            ),
            (SENSOR, RAIN_GAUGE),
        )
    if name == "RECOVERY":
        return ScenarioDefinition(
            name,
            "Rainfall and water depth decline while flood evidence resolves.",
            timedelta(minutes=30),
            (
                _health(0, SensorStatus.ONLINE),
                _rainfall(0, 35),
                _water(0, 32),
                _zone(0, EventType.FLOOD_ZONE_ACTIVATED, "SEVERE", 0.95),
                _rainfall(10, 12),
                _water(15, 10),
                _zone(20, EventType.FLOOD_ZONE_UPDATED, "MODERATE", 0.4),
                _incident(25, EventType.INCIDENT_RESOLVED, "RESOLVED"),
                _zone(30, EventType.FLOOD_ZONE_CLEARED, "LOW", 0.0),
            ),
            (SENSOR, RAIN_GAUGE),
        )
    raise KeyError(f"unknown simulation scenario: {name}")


def available_scenarios() -> tuple[str, ...]:
    return ("NORMAL", "MODERATE_RAIN", "SEVERE_RAIN", "FLASH_FLOOD", "SENSOR_OUTAGE", "RECOVERY")


def get_scenario(name: str, rng: Random) -> ScenarioDefinition:
    return _definition(name.upper(), rng)

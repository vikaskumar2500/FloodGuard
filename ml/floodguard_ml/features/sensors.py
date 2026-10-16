"""Sensor and water depth feature computation.

Contract:
Only sensor readings with timestamp <= T are included.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class SensorRecord:
    timestamp: datetime
    water_depth_cm: float | None
    quality: str = "GOOD"
    sensor_id: str = "default"


QUALITY_CONFIDENCE_MAP = {
    "GOOD": 1.0,
    "VERIFIED": 1.0,
    "SUSPECT": 0.5,
    "SIMULATED": 0.5,
    "ESTIMATED": 0.5,
    "INVALID": 0.0,
}


def compute_sensor_features(
    readings: list[SensorRecord],
    observation_time: datetime,
    freshness_seconds: float = 3600.0,
) -> dict[str, Any]:
    """Compute current water depth, depth trend, and sensor confidence at observation_time T."""
    past_readings = [r for r in readings if r.timestamp <= observation_time]

    if not past_readings:
        return {
            "water_depth_current_cm": None,
            "water_depth_trend_cm_per_min": None,
            "water_depth_max_30m_cm": None,
            "nearby_sensor_count": 0,
            "sensor_confidence": None,
            "sensor_freshness_seconds": None,
        }

    past_readings.sort(key=lambda r: r.timestamp)
    latest = past_readings[-1]
    age_seconds = (observation_time - latest.timestamp).total_seconds()
    is_fresh = age_seconds <= freshness_seconds

    current_depth = latest.water_depth_cm if is_fresh else None
    confidence = (
        QUALITY_CONFIDENCE_MAP.get(latest.quality.upper(), 0.5) if is_fresh else None
    )

    # Sensor count (distinct sensor IDs seen in recent history)
    unique_sensors = {r.sensor_id for r in past_readings}
    sensor_count = len(unique_sensors)

    # Depth trend: compare latest reading to immediately preceding reading with non-null depth
    depth_trend: float | None = None
    readings_with_depth = [r for r in past_readings if r.water_depth_cm is not None]
    if len(readings_with_depth) >= 2:
        prev = readings_with_depth[-2]
        curr = readings_with_depth[-1]
        dt_minutes = (curr.timestamp - prev.timestamp).total_seconds() / 60.0
        if dt_minutes > 0.01:  # avoid divide by zero
            trend = (curr.water_depth_cm - prev.water_depth_cm) / dt_minutes
            depth_trend = round(trend, 4)

    # Max water depth in past 30 minutes
    window_30m = observation_time - timedelta(minutes=30)
    recent_depths = [
        r.water_depth_cm
        for r in past_readings
        if r.timestamp > window_30m and r.water_depth_cm is not None
    ]
    max_depth_30m = max(recent_depths) if recent_depths else None

    return {
        "water_depth_current_cm": current_depth,
        "water_depth_trend_cm_per_min": depth_trend,
        "water_depth_max_30m_cm": max_depth_30m,
        "nearby_sensor_count": sensor_count,
        "sensor_confidence": confidence,
        "sensor_freshness_seconds": round(age_seconds, 1),
    }


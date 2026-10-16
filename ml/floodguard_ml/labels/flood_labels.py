"""Prediction target label calculation.

Critical Invariant 1:
The label is derived strictly from future events in the interval:
    T < event_timestamp <= T + horizon

Events at or before T (<= T) are NEVER considered for the label.
Events beyond the horizon (> T + horizon) are NEVER considered.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class GroundTruthEvent:
    timestamp: datetime
    water_depth_cm: float | None = None
    severity: str | None = None  # "LOW", "MODERATE", "HIGH", "SEVERE"
    event_type: str = "sensor"  # "sensor", "flood_zone", "incident"


SEVERE_SEVERITIES = {"HIGH", "SEVERE"}


def compute_flood_label(
    events: list[GroundTruthEvent],
    observation_time: datetime,
    horizon_minutes: int = 30,
    water_depth_threshold_cm: float = 15.0,
) -> int:
    """Compute binary flood label (0 or 1) for observation_time T over horizon H.

    Label is 1 if in the future interval (T, T + horizon]:
    - Any sensor reading has water_depth_cm >= water_depth_threshold_cm
    - Any flood zone or incident has severity in {"HIGH", "SEVERE"}

    Returns 0 otherwise.
    """
    horizon_end = observation_time + timedelta(minutes=horizon_minutes)

    # Strictly filter events in (observation_time, horizon_end]
    future_events = [
        e for e in events if observation_time < e.timestamp <= horizon_end
    ]

    for event in future_events:
        # Check water depth threshold
        if (
            event.water_depth_cm is not None
            and event.water_depth_cm >= water_depth_threshold_cm
        ):
            return 1

        # Check severity threshold for flood zones and incidents
        if event.severity and event.severity.upper() in SEVERE_SEVERITIES:
            return 1

    return 0


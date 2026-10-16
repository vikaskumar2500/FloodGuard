"""Missingness indicators and historical flood count computation.

Preserves Critical Invariant 2: Missing != Zero.
Explicit boolean indicators track whether readings were absent from the source.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def compute_missingness_indicators(
    rainfall_rate: float | None,
    water_depth: float | None,
    temperature: float | None,
) -> dict[str, bool]:
    """Compute explicit boolean missingness flags.

    Critical rule:
    0.0 is an observed value -> indicator is False.
    None is a missing value  -> indicator is True.
    """
    return {
        "is_rainfall_missing": rainfall_rate is None,
        "is_water_depth_missing": water_depth is None,
        "is_temperature_missing": temperature is None,
    }


def compute_historical_features(
    past_flood_events: list[datetime],
    observation_time: datetime,
) -> dict[str, Any]:
    """Count historical flood events on this edge in the prior 30 days (<= T)."""
    window_start = observation_time - timedelta(days=30)
    count_30d = sum(
        1 for t in past_flood_events if window_start <= t <= observation_time
    )
    return {
        "historical_flood_count_30d": count_30d,
    }


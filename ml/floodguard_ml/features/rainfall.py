"""Environmental and rolling rainfall feature computation.

Contract:
All observations considered must have timestamp <= T.
Future observations (> T) are strictly filtered out to prevent data leakage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class WeatherRecord:
    timestamp: datetime
    rainfall_mm_per_hour: float | None
    temperature_c: float | None = None
    humidity_percent: float | None = None
    wind_speed_mps: float | None = None


def compute_rainfall_features(
    observations: list[WeatherRecord],
    observation_time: datetime,
    freshness_seconds: float = 3600.0,
) -> dict[str, Any]:
    """Compute current weather and rolling rainfall accumulation for observation_time T.

    Strict contract:
    Only observations with timestamp <= observation_time are included.
    """
    # 1. Filter out any future observations
    past_obs = [obs for obs in observations if obs.timestamp <= observation_time]

    if not past_obs:
        return {
            "rainfall_rate_now_mm_h": None,
            "rainfall_accum_15m_mm": None,
            "rainfall_accum_30m_mm": None,
            "rainfall_accum_1h_mm": None,
            "rainfall_accum_3h_mm": None,
            "temperature_c": None,
            "humidity_pct": None,
            "wind_speed_mps": None,
            "weather_freshness_seconds": None,
        }

    # Sort past observations chronologically
    past_obs.sort(key=lambda o: o.timestamp)
    latest = past_obs[-1]
    age_seconds = (observation_time - latest.timestamp).total_seconds()

    # If the latest reading is older than freshness threshold, mark current as missing
    is_fresh = age_seconds <= freshness_seconds

    rate_now = latest.rainfall_mm_per_hour if is_fresh else None
    temp_now = latest.temperature_c if is_fresh else None
    hum_now = latest.humidity_percent if is_fresh else None
    wind_now = latest.wind_speed_mps if is_fresh else None

    # Compute rolling accumulations over specific lookback windows
    def _accumulate_window(window_minutes: int) -> float | None:
        window_start = observation_time - timedelta(minutes=window_minutes)
        window_obs = [o for o in past_obs if o.timestamp > window_start]
        valid_rains = [o.rainfall_mm_per_hour for o in window_obs if o.rainfall_mm_per_hour is not None]
        if not valid_rains:
            return None
        # Convert hourly rates to accumulated mm over discrete slices, or direct sum if rates
        # If hourly rate given per point in minute interval dt:
        # For simplicity and standardization across simulator/API, assume each observation
        # represents an hourly rate applied over the delta interval, or average hourly rate.
        # Standard: sum of (rate * (interval_h)) or direct slice sum:
        # When rate (mm/h) is recorded at 5-minute intervals: rate * (5 / 60) hours.
        # If single reading: rate * (window / 60).
        # To be robust across variable sampling:
        total_mm = sum(r * (window_minutes / 60.0) / max(len(valid_rains), 1) for r in valid_rains)
        return round(total_mm, 3)

    return {
        "rainfall_rate_now_mm_h": rate_now,
        "rainfall_accum_15m_mm": _accumulate_window(15),
        "rainfall_accum_30m_mm": _accumulate_window(30),
        "rainfall_accum_1h_mm": _accumulate_window(60),
        "rainfall_accum_3h_mm": _accumulate_window(180),
        "temperature_c": temp_now,
        "humidity_pct": hum_now,
        "wind_speed_mps": wind_now,
        "weather_freshness_seconds": round(age_seconds, 1),
    }


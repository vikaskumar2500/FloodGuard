"""Canonical normalized domain models for the environmental adapter layer.

Critical semantic rule:
    rainfall_mm_per_hour = None   →  provider did NOT supply rainfall (MISSING)
    rainfall_mm_per_hour = 0.0   →  explicit observation of NO rain (ZERO)

These two states are never interchangeable anywhere in the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class DataSourceState(StrEnum):
    """Describes how an EnvironmentalObservation was obtained."""

    LIVE = "LIVE"  # Fresh data retrieved directly from the provider API
    CACHE_FRESH = "CACHE_FRESH"  # Returned from Redis cache within freshness window
    CACHE_STALE = "CACHE_STALE"  # Returned from Redis cache beyond freshness but within expiry
    MOCK = "MOCK"  # Produced by the deterministic mock provider
    UNAVAILABLE = "UNAVAILABLE"  # Provider failed and no usable cache entry exists


@dataclass(frozen=True)
class EnvironmentalObservation:
    """Normalized, provider-agnostic environmental observation.

    Fields:
        provider: Short provider identifier (e.g. "open_meteo", "mock").
        external_id: Deterministic unique ID for deduplication across provider restarts.
        latitude: WGS-84 decimal degrees.
        longitude: WGS-84 decimal degrees.
        observed_at: Timestamp the observation was recorded by the sensor/model.
        received_at: Timestamp this process obtained the observation.
        rainfall_mm_per_hour: Rainfall rate in mm/h, or None if the provider did not supply it.
        temperature_c: Air temperature in °C, or None if unavailable.
        humidity_percent: Relative humidity 0–100, or None if unavailable.
        wind_speed_mps: Wind speed in m/s, or None if unavailable.
        source_quality: Provider-specific quality indicator (e.g. "good", "estimated").
        data_source_state: How this observation was obtained.
        raw_metadata: Unmodified provider response fragment for debugging; never forwarded to clients.
    """

    provider: str
    external_id: str
    latitude: float
    longitude: float
    observed_at: datetime
    received_at: datetime
    # CRITICAL: None means MISSING, 0.0 means explicit zero — never conflate.
    rainfall_mm_per_hour: float | None
    temperature_c: float | None
    humidity_percent: float | None
    wind_speed_mps: float | None
    source_quality: str
    data_source_state: DataSourceState
    raw_metadata: dict[str, Any] | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.humidity_percent is not None and not (0.0 <= self.humidity_percent <= 100.0):
            raise ValueError(f"humidity_percent must be 0–100, got {self.humidity_percent}")
        if self.rainfall_mm_per_hour is not None and self.rainfall_mm_per_hour < 0.0:
            raise ValueError(f"rainfall_mm_per_hour must be ≥ 0, got {self.rainfall_mm_per_hour}")
        if self.wind_speed_mps is not None and self.wind_speed_mps < 0.0:
            raise ValueError(f"wind_speed_mps must be ≥ 0, got {self.wind_speed_mps}")

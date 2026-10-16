"""Versioned feature configuration for ML dataset generation."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field


class FeatureConfig(BaseModel):
    """Configuration governing feature generation, prediction horizon, and sampling."""

    feature_version: str = Field(default="v1", description="Semantic feature schema version")
    prediction_horizon_minutes: int = Field(
        default=30, gt=0, le=1440, description="Future prediction horizon in minutes"
    )
    sampling_interval_minutes: int = Field(
        default=5, gt=0, le=60, description="Temporal sampling step between dataset rows"
    )
    weather_lookback_minutes: int = Field(
        default=180, gt=0, description="Max historical lookback window for weather aggregation (3h)"
    )
    weather_freshness_seconds: float = Field(
        default=3600.0, gt=0, description="Max age allowed before weather data is considered missing"
    )
    sensor_freshness_seconds: float = Field(
        default=3600.0, gt=0, description="Max age allowed before sensor reading is considered missing"
    )
    flood_water_depth_threshold_cm: float = Field(
        default=15.0, gt=0, description="Water depth threshold in cm that defines flooding"
    )
    rainfall_change_threshold_mm_h: float = Field(
        default=0.5, ge=0, description="Rainfall delta considered material"
    )
    include_road_features: bool = Field(default=True, description="Include road topology features")
    include_temporal_features: bool = Field(default=True, description="Include calendar/temporal features")
    include_missingness_indicators: bool = Field(
        default=True, description="Include explicit boolean flags for missing data"
    )
    split_train_ratio: float = Field(default=0.70, gt=0, lt=1)
    split_val_ratio: float = Field(default=0.15, gt=0, lt=1)
    split_test_ratio: float = Field(default=0.15, gt=0, lt=1)

    model_config = {"frozen": True}

    def compute_config_hash(self) -> str:
        """Return a deterministic SHA-256 hash of this configuration."""
        canonical = json.dumps(self.model_dump(), sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


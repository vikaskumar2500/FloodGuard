"""Unit tests for feature calculation modules."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from floodguard_ml.features.indicators import (
    compute_historical_features,
    compute_missingness_indicators,
)
from floodguard_ml.features.rainfall import WeatherRecord, compute_rainfall_features
from floodguard_ml.features.road import RoadEdgeAttributes, compute_road_features
from floodguard_ml.features.sensors import SensorRecord, compute_sensor_features
from floodguard_ml.features.temporal import compute_temporal_features, get_season_category


class TestTemporalFeatures:
    def test_calendar_features(self) -> None:
        dt = datetime(2026, 7, 15, 14, 30, tzinfo=timezone.utc)
        feats = compute_temporal_features(dt)
        assert feats["hour_of_day"] == 14
        assert feats["day_of_week"] == 2  # Wednesday
        assert feats["month"] == 7
        assert feats["season_category"] == "MONSOON"

    def test_season_mapping(self) -> None:
        assert get_season_category(7) == "MONSOON"
        assert get_season_category(8) == "MONSOON"
        assert get_season_category(10) == "POST_MONSOON"
        assert get_season_category(1) == "DRY"
        assert get_season_category(4) == "PRE_MONSOON"


class TestRainfallFeatures:
    def test_missing_vs_zero_rainfall(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

        # 1. Zero rainfall explicitly recorded
        obs_zero = [WeatherRecord(t0, rainfall_mm_per_hour=0.0)]
        f_zero = compute_rainfall_features(obs_zero, t0)
        assert f_zero["rainfall_rate_now_mm_h"] == 0.0
        assert f_zero["rainfall_rate_now_mm_h"] is not None

        # 2. Missing rainfall (None)
        obs_none = [WeatherRecord(t0, rainfall_mm_per_hour=None)]
        f_none = compute_rainfall_features(obs_none, t0)
        assert f_none["rainfall_rate_now_mm_h"] is None

        # 3. Empty observation list
        f_empty = compute_rainfall_features([], t0)
        assert f_empty["rainfall_rate_now_mm_h"] is None

    def test_rolling_accumulation(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        obs = [
            WeatherRecord(t0 - timedelta(minutes=10), rainfall_mm_per_hour=24.0),
            WeatherRecord(t0 - timedelta(minutes=5), rainfall_mm_per_hour=36.0),
            WeatherRecord(t0, rainfall_mm_per_hour=12.0),
        ]
        feats = compute_rainfall_features(obs, t0)
        assert feats["rainfall_rate_now_mm_h"] == 12.0
        assert feats["rainfall_accum_15m_mm"] is not None
        assert feats["rainfall_accum_15m_mm"] > 0
        assert feats["rainfall_accum_1h_mm"] is not None

    def test_stale_weather_data_marked_missing(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        # Observation 2 hours old
        obs_old = [WeatherRecord(t0 - timedelta(hours=2), rainfall_mm_per_hour=20.0)]
        feats = compute_rainfall_features(obs_old, t0, freshness_seconds=3600.0)
        # Exceeds 1h freshness threshold -> current rate is None
        assert feats["rainfall_rate_now_mm_h"] is None


class TestSensorFeatures:
    def test_sensor_depth_and_trend(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        readings = [
            SensorRecord(t0 - timedelta(minutes=10), water_depth_cm=5.0, quality="GOOD", sensor_id="s1"),
            SensorRecord(t0, water_depth_cm=15.0, quality="GOOD", sensor_id="s1"),
        ]
        feats = compute_sensor_features(readings, t0)
        assert feats["water_depth_current_cm"] == 15.0
        # Trend: (15 - 5) / 10 min = 1.0 cm/min
        assert feats["water_depth_trend_cm_per_min"] == 1.0
        assert feats["water_depth_max_30m_cm"] == 15.0
        assert feats["nearby_sensor_count"] == 1
        assert feats["sensor_confidence"] == 1.0

    def test_sensor_max_depth_window(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        readings = [
            SensorRecord(t0 - timedelta(minutes=40), water_depth_cm=30.0),  # outside 30m window
            SensorRecord(t0 - timedelta(minutes=10), water_depth_cm=12.0),
            SensorRecord(t0, water_depth_cm=8.0),
        ]
        feats = compute_sensor_features(readings, t0)
        assert feats["water_depth_current_cm"] == 8.0
        assert feats["water_depth_max_30m_cm"] == 12.0  # 30.0 was outside 30m window


class TestRoadAndHistoricalFeatures:
    def test_road_attributes(self) -> None:
        attr = RoadEdgeAttributes(
            edge_id="e1", road_class="primary", length_m=150.5, speed_limit_mps=16.67, is_bridge=True
        )
        feats = compute_road_features(attr, dist_to_flood_zone_m=45.0)
        assert feats["road_class"] == "primary"
        assert feats["length_m"] == 150.5
        assert feats["is_bridge"] is True
        assert feats["is_tunnel"] is False
        assert feats["dist_to_flood_zone_m"] == 45.0

    def test_missingness_indicators(self) -> None:
        # Zero rainfall is not missing
        ind1 = compute_missingness_indicators(rainfall_rate=0.0, water_depth=10.0, temperature=25.0)
        assert ind1["is_rainfall_missing"] is False
        assert ind1["is_water_depth_missing"] is False
        assert ind1["is_temperature_missing"] is False

        # None is missing
        ind2 = compute_missingness_indicators(rainfall_rate=None, water_depth=None, temperature=None)
        assert ind2["is_rainfall_missing"] is True
        assert ind2["is_water_depth_missing"] is True
        assert ind2["is_temperature_missing"] is True

    def test_historical_flood_count(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        history = [
            t0 - timedelta(days=10),
            t0 - timedelta(days=20),
            t0 - timedelta(days=45),  # older than 30d
        ]
        feats = compute_historical_features(history, t0)
        assert feats["historical_flood_count_30d"] == 2


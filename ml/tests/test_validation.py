"""Unit tests for dataset schema and quality validation."""

from __future__ import annotations

import pytest

from floodguard_ml.datasets.validation import DatasetValidationError, validate_dataset


def _make_valid_row(edge_id: str = "e1", ts: str = "2026-10-08T12:00:00Z") -> dict:
    return {
        "edge_id": edge_id,
        "observation_time": ts,
        "prediction_horizon_minutes": 30,
        "source_type": "SYNTHETIC",
        "rainfall_rate_now_mm_h": 10.0,
        "rainfall_accum_15m_mm": 2.5,
        "rainfall_accum_30m_mm": 5.0,
        "rainfall_accum_1h_mm": 10.0,
        "rainfall_accum_3h_mm": 20.0,
        "temperature_c": 28.0,
        "humidity_pct": 80.0,
        "wind_speed_mps": 3.0,
        "weather_freshness_seconds": 60.0,
        "water_depth_current_cm": 5.0,
        "water_depth_trend_cm_per_min": 0.1,
        "water_depth_max_30m_cm": 5.0,
        "nearby_sensor_count": 1,
        "sensor_confidence": 1.0,
        "sensor_freshness_seconds": 60.0,
        "is_rainfall_missing": False,
        "is_water_depth_missing": False,
        "is_temperature_missing": False,
        "road_class": "primary",
        "length_m": 120.0,
        "speed_limit_mps": 13.88,
        "is_bridge": False,
        "is_tunnel": False,
        "edge_elevation_m": 10.0,
        "dist_to_flood_zone_m": None,
        "hour_of_day": 12,
        "day_of_week": 3,
        "month": 10,
        "season_category": "POST_MONSOON",
        "historical_flood_count_30d": 0,
        "target_flooded_within_horizon": 0,
    }


class TestValidation:
    def test_valid_dataset_passes_validation(self) -> None:
        rows = [
            _make_valid_row("e1", "2026-10-08T12:00:00Z"),
            _make_valid_row("e2", "2026-10-08T12:00:00Z"),
        ]
        rows[1]["target_flooded_within_horizon"] = 1

        report = validate_dataset(rows)
        assert report.total_rows == 2
        assert report.duplicate_rows == 0
        assert report.positive_count == 1
        assert report.positive_rate == 0.5
        assert "rainfall_rate_now_mm_h" in report.numeric_stats

    def test_duplicate_row_rejected(self) -> None:
        rows = [
            _make_valid_row("e1", "2026-10-08T12:00:00Z"),
            _make_valid_row("e1", "2026-10-08T12:00:00Z"),  # exact duplicate
        ]
        with pytest.raises(DatasetValidationError, match="duplicate"):
            validate_dataset(rows)

    def test_infinite_value_rejected(self) -> None:
        row = _make_valid_row()
        row["rainfall_rate_now_mm_h"] = float("inf")
        with pytest.raises(DatasetValidationError, match="NaN or Inf"):
            validate_dataset([row])

    def test_negative_physical_value_rejected(self) -> None:
        row = _make_valid_row()
        row["water_depth_current_cm"] = -10.0
        with pytest.raises(DatasetValidationError, match="negative water depth"):
            validate_dataset([row])

    def test_humidity_out_of_bounds_rejected(self) -> None:
        row = _make_valid_row()
        row["humidity_pct"] = 105.0
        with pytest.raises(DatasetValidationError, match="humidity out of bounds"):
            validate_dataset([row])


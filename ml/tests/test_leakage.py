"""Automated leakage prevention tests.

Critical Invariant 1:
Features at T must never incorporate information from > T.
Splits must strictly maintain chronological non-overlapping boundaries.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from floodguard_ml.datasets.splits import time_based_split
from floodguard_ml.features.rainfall import WeatherRecord, compute_rainfall_features
from floodguard_ml.features.schema import FEATURE_SCHEMA_V1
from floodguard_ml.features.sensors import SensorRecord, compute_sensor_features


class TestLeakagePrevention:
    def test_future_rainfall_spike_does_not_leak_into_current_features(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

        # Baseline observations up to T0
        baseline_obs = [
            WeatherRecord(t0 - timedelta(minutes=10), rainfall_mm_per_hour=5.0),
            WeatherRecord(t0, rainfall_mm_per_hour=5.0),
        ]
        feats_before_spike = compute_rainfall_features(baseline_obs, t0)

        # Now simulate a massive deluge in the future (T + 5 min, T + 10 min)
        obs_with_future_spike = list(baseline_obs) + [
            WeatherRecord(t0 + timedelta(minutes=5), rainfall_mm_per_hour=150.0),
            WeatherRecord(t0 + timedelta(minutes=10), rainfall_mm_per_hour=200.0),
        ]
        feats_after_spike = compute_rainfall_features(obs_with_future_spike, t0)

        # The features evaluated at T0 MUST be completely identical
        assert feats_before_spike == feats_after_spike
        assert feats_after_spike["rainfall_rate_now_mm_h"] == 5.0
        assert feats_after_spike["rainfall_accum_15m_mm"] == pytest.approx(
            feats_before_spike["rainfall_accum_15m_mm"]
        )

    def test_future_water_depth_spike_does_not_leak(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)

        baseline_sensors = [
            SensorRecord(t0 - timedelta(minutes=10), water_depth_cm=2.0),
            SensorRecord(t0, water_depth_cm=3.0),
        ]
        feats_before = compute_sensor_features(baseline_sensors, t0)

        # Massive future water depth surge (e.g. 50cm flood at T + 10min)
        sensors_with_future = list(baseline_sensors) + [
            SensorRecord(t0 + timedelta(minutes=10), water_depth_cm=50.0),
            SensorRecord(t0 + timedelta(minutes=20), water_depth_cm=75.0),
        ]
        feats_after = compute_sensor_features(sensors_with_future, t0)

        assert feats_before == feats_after
        assert feats_after["water_depth_current_cm"] == 3.0
        assert feats_after["water_depth_max_30m_cm"] == 3.0

    def test_forbidden_target_proxy_columns_not_in_features(self) -> None:
        """Verify no target leakage columns are declared as features in schema."""
        forbidden_substrings = [
            "target",
            "future",
            "ground_truth",
            "label",
            "next_",
        ]
        for feat_name in FEATURE_SCHEMA_V1.feature_names:
            for forbidden in forbidden_substrings:
                assert forbidden not in feat_name.lower(), (
                    f"Forbidden leakage pattern '{forbidden}' found in feature '{feat_name}'"
                )

    def test_split_temporal_leakage_prevented(self) -> None:
        """Verify max(train_time) < min(val_time) and max(val_time) < min(test_time)."""
        base_t = datetime(2026, 10, 8, 0, 0, tzinfo=timezone.utc)
        # Create 100 rows spaced 5 minutes apart across 2 edges
        records = []
        for i in range(100):
            ts = (base_t + timedelta(minutes=i * 5)).isoformat()
            records.append({
                "edge_id": "edge-1",
                "observation_time": ts,
                "target_flooded_within_horizon": 0,
            })
            records.append({
                "edge_id": "edge-2",
                "observation_time": ts,
                "target_flooded_within_horizon": 0,
            })

        splits = time_based_split(records, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15)

        train_max = max(r["observation_time"] for r in splits.train_records)
        val_min = min(r["observation_time"] for r in splits.val_records)
        val_max = max(r["observation_time"] for r in splits.val_records)
        test_min = min(r["observation_time"] for r in splits.test_records)

        assert train_max < val_min, f"Train overlaps with Val: {train_max} >= {val_min}"
        assert val_max < test_min, f"Val overlaps with Test: {val_max} >= {test_min}"


"""Unit tests for prediction target label generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from floodguard_ml.labels.flood_labels import GroundTruthEvent, compute_flood_label


class TestFloodLabels:
    def test_future_water_depth_triggers_positive_label(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        # Event in the future (T + 15 min) with 20 cm water depth (threshold is 15 cm)
        events = [
            GroundTruthEvent(t0 + timedelta(minutes=15), water_depth_cm=20.0),
        ]
        label = compute_flood_label(events, observation_time=t0, horizon_minutes=30)
        assert label == 1

    def test_past_depth_does_not_trigger_label(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        # Major flood in the PAST (T - 5 min), but future is clear
        events = [
            GroundTruthEvent(t0 - timedelta(minutes=5), water_depth_cm=50.0),
        ]
        label = compute_flood_label(events, observation_time=t0, horizon_minutes=30)
        assert label == 0

    def test_beyond_horizon_does_not_trigger_label(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        # Flood occurs 45 minutes in the future (outside 30m horizon)
        events = [
            GroundTruthEvent(t0 + timedelta(minutes=45), water_depth_cm=50.0),
        ]
        label = compute_flood_label(events, observation_time=t0, horizon_minutes=30)
        assert label == 0

    def test_sub_threshold_water_depth_yields_negative(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        # Water depth 8cm in future (below 15cm threshold)
        events = [
            GroundTruthEvent(t0 + timedelta(minutes=10), water_depth_cm=8.0),
        ]
        label = compute_flood_label(events, observation_time=t0, horizon_minutes=30)
        assert label == 0

    def test_severe_flood_zone_triggers_positive(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        events = [
            GroundTruthEvent(t0 + timedelta(minutes=10), severity="HIGH", event_type="flood_zone"),
        ]
        assert compute_flood_label(events, t0, horizon_minutes=30) == 1

    def test_low_severity_does_not_trigger_positive(self) -> None:
        t0 = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        events = [
            GroundTruthEvent(t0 + timedelta(minutes=10), severity="LOW", event_type="flood_zone"),
        ]
        assert compute_flood_label(events, t0, horizon_minutes=30) == 0


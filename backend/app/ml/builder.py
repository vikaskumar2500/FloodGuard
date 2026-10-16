"""Online Feature Builder for real-time and routing ML inference.

Guarantees ZERO training-serving skew by directly invoking shared
feature computation functions from floodguard_ml.features.*.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from floodguard_ml.features.indicators import (
    compute_historical_features,
    compute_missingness_indicators,
)
from floodguard_ml.features.rainfall import WeatherRecord, compute_rainfall_features
from floodguard_ml.features.road import RoadEdgeAttributes, compute_road_features
from floodguard_ml.features.sensors import SensorRecord, compute_sensor_features
from floodguard_ml.features.temporal import compute_temporal_features
from floodguard_ml.models.selection import audit_feature_leakage

from app.risk.models import EdgeEvidence, SensorEvidence, WeatherEvidence
from app.routing.models import RoutingEdge


class OnlineFeatureBuilder:
    """Constructs ModelFeaturesV1-compatible input records from live routing evidence."""

    feature_version: str = "v1"

    def __init__(
        self,
        weather_freshness_seconds: float = 3600.0,
        sensor_freshness_seconds: float = 3600.0,
    ) -> None:
        self.weather_freshness_seconds = weather_freshness_seconds
        self.sensor_freshness_seconds = sensor_freshness_seconds

    def _convert_weather_evidence(
        self, weather_evidence: list[WeatherEvidence]
    ) -> list[WeatherRecord]:
        records: list[WeatherRecord] = []
        for w in weather_evidence:
            rate: float | None = w.rainfall_mm
            if rate is not None and w.observation_interval_minutes:
                rate = rate * 60.0 / w.observation_interval_minutes
            records.append(
                WeatherRecord(
                    timestamp=w.observed_at,
                    rainfall_mm_per_hour=rate,
                )
            )
        return records

    def _convert_sensor_evidence(self, sensor_evidence: list[SensorEvidence]) -> list[SensorRecord]:
        return [
            SensorRecord(
                timestamp=s.observed_at,
                water_depth_cm=s.water_depth_cm,
                quality=s.quality,
            )
            for s in sensor_evidence
        ]

    def build_features(
        self,
        edge: RoutingEdge | RoadEdgeAttributes | dict[str, Any],
        now: datetime,
        evidence: EdgeEvidence | None = None,
        weather_records: list[WeatherRecord] | None = None,
        sensor_records: list[SensorRecord] | None = None,
        past_flood_events: list[datetime] | None = None,
    ) -> dict[str, Any]:
        """Build canonical 29-feature dictionary for a single edge at observation time T.

        Contract:
        - Only observations with timestamp <= now are evaluated.
        - Zero future leakage: no ground truth, future labels, or spatial memorizers.
        - Missing != Zero semantics preserved.
        """
        # 1. Resolve road attributes
        road_attr: RoadEdgeAttributes
        if isinstance(edge, RoadEdgeAttributes):
            road_attr = edge
        elif isinstance(edge, RoutingEdge):
            speed_limit = (
                edge.distance_m / edge.base_travel_time_s if edge.base_travel_time_s > 0 else 13.88
            )
            road_attr = RoadEdgeAttributes(
                edge_id=str(edge.id),
                road_class="primary",  # Default road class if not annotated on edge
                length_m=edge.distance_m,
                speed_limit_mps=round(speed_limit, 2),
                is_bridge=False,
                is_tunnel=False,
                elevation_m=None,
            )
        elif isinstance(edge, dict):
            road_attr = RoadEdgeAttributes(
                edge_id=str(edge.get("edge_id", "default")),
                road_class=edge.get("road_class", "primary"),
                length_m=float(edge.get("length_m", 100.0)),
                speed_limit_mps=edge.get("speed_limit_mps", 13.88),
                is_bridge=bool(edge.get("is_bridge", False)),
                is_tunnel=bool(edge.get("is_tunnel", False)),
                elevation_m=edge.get("elevation_m"),
            )
        else:
            raise TypeError(f"Unsupported edge type: {type(edge)}")

        # 2. Resolve weather and sensor records
        final_weather: list[WeatherRecord] = []
        if weather_records is not None:
            final_weather = weather_records
        elif evidence is not None and evidence.weather:
            final_weather = self._convert_weather_evidence(evidence.weather)

        final_sensors: list[SensorRecord] = []
        if sensor_records is not None:
            final_sensors = sensor_records
        elif evidence is not None and evidence.sensors:
            final_sensors = self._convert_sensor_evidence(evidence.sensors)

        flood_history = past_flood_events or []

        # 3. Compute component features using shared Phase 11 functions
        rainfall_feats = compute_rainfall_features(
            final_weather,
            observation_time=now,
            freshness_seconds=self.weather_freshness_seconds,
        )

        sensor_feats = compute_sensor_features(
            final_sensors,
            observation_time=now,
            freshness_seconds=self.sensor_freshness_seconds,
        )

        missing_feats = compute_missingness_indicators(
            rainfall_rate=rainfall_feats["rainfall_rate_now_mm_h"],
            water_depth=sensor_feats["water_depth_current_cm"],
            temperature=rainfall_feats["temperature_c"],
        )

        road_feats = compute_road_features(road_attr)
        # Exclude dist_to_flood_zone_m from model input features as per ModelFeaturesV1
        road_feats.pop("dist_to_flood_zone_m", None)

        temporal_feats = compute_temporal_features(now)

        hist_feats = compute_historical_features(
            past_flood_events=flood_history,
            observation_time=now,
        )

        # 4. Assemble complete feature vector
        record: dict[str, Any] = {
            **rainfall_feats,
            **sensor_feats,
            **missing_feats,
            **road_feats,
            **temporal_feats,
            **hist_feats,
        }

        # 5. Audit feature keys for zero leakage
        audit_feature_leakage(tuple(record.keys()))

        return record

"""ML Dataset Builder engine.

Assembles training records across edges and timestamps.
Enforces the feature timestamp contract (features <= T, label > T).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from floodguard_ml.config.feature_config import FeatureConfig
from floodguard_ml.datasets.sources import DataSourceAdapter, SourceBundle
from floodguard_ml.features.indicators import (
    compute_historical_features,
    compute_missingness_indicators,
)
from floodguard_ml.features.rainfall import compute_rainfall_features
from floodguard_ml.features.road import compute_road_features
from floodguard_ml.features.sensors import compute_sensor_features
from floodguard_ml.features.temporal import compute_temporal_features
from floodguard_ml.labels.flood_labels import compute_flood_label

logger = logging.getLogger("floodguard_ml.builder")


class DatasetBuilder:
    """Constructs tabular ML dataset rows from a source bundle."""

    def __init__(self, config: FeatureConfig) -> None:
        self.config = config

    def build_records(
        self,
        source: DataSourceAdapter,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Extract and assemble tabular dataset records."""
        bundle: SourceBundle = source.load_data(start_time, end_time)

        t_start = start_time or bundle.min_time
        t_end = end_time or bundle.max_time

        if t_start is None or t_end is None or t_start > t_end:
            logger.warning("Empty time range for dataset build.")
            return []

        step = timedelta(minutes=self.config.sampling_interval_minutes)
        horizon = self.config.prediction_horizon_minutes

        # We can sample observation times up to t_end - horizon
        # so that ground truth events in (T, T + H] are fully within data bounds
        sample_cutoff = t_end - timedelta(minutes=horizon)
        if sample_cutoff < t_start:
            sample_cutoff = t_end

        records: list[dict[str, Any]] = []
        current_time = t_start

        while current_time <= sample_cutoff:
            for edge_id, road_attr in bundle.roads.items():
                weather_obs = bundle.weather_by_edge.get(edge_id, [])
                sensor_obs = bundle.sensors_by_edge.get(edge_id, [])
                gt_events = bundle.ground_truth_by_edge.get(edge_id, [])
                flood_history = bundle.past_flood_events.get(edge_id, [])

                # 1. Environmental & Rainfall features (STRICTLY <= T)
                rainfall_feats = compute_rainfall_features(
                    weather_obs,
                    observation_time=current_time,
                    freshness_seconds=self.config.weather_freshness_seconds,
                )

                # 2. Sensor features (STRICTLY <= T)
                sensor_feats = compute_sensor_features(
                    sensor_obs,
                    observation_time=current_time,
                    freshness_seconds=self.config.sensor_freshness_seconds,
                )

                # 3. Missingness indicators
                missing_feats = compute_missingness_indicators(
                    rainfall_rate=rainfall_feats["rainfall_rate_now_mm_h"],
                    water_depth=sensor_feats["water_depth_current_cm"],
                    temperature=rainfall_feats["temperature_c"],
                )

                # 4. Road features
                road_feats = compute_road_features(road_attr)

                # 5. Temporal features
                temporal_feats = compute_temporal_features(current_time)

                # 6. Historical features (STRICTLY <= T)
                hist_feats = compute_historical_features(
                    past_flood_events=flood_history,
                    observation_time=current_time,
                )

                # 7. Prediction target label (STRICTLY in (T, T + horizon])
                label = compute_flood_label(
                    events=gt_events,
                    observation_time=current_time,
                    horizon_minutes=horizon,
                    water_depth_threshold_cm=self.config.flood_water_depth_threshold_cm,
                )

                row: dict[str, Any] = {
                    # Identification & Provenance metadata
                    "edge_id": edge_id,
                    "observation_time": current_time.isoformat(),
                    "prediction_horizon_minutes": horizon,
                    "source_type": bundle.source_type,
                    # Features
                    **rainfall_feats,
                    **sensor_feats,
                    **missing_feats,
                    **road_feats,
                    **temporal_feats,
                    **hist_feats,
                    # Label
                    "target_flooded_within_horizon": label,
                }
                records.append(row)

            current_time += step

        logger.info(
            "dataset_records_built",
            extra={"records": len(records), "source_type": bundle.source_type},
        )
        return records


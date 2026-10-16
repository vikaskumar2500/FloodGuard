"""Feature selection and leakage audit for FloodGuard ML models.

Specification: MODEL_FEATURES_V1
"""

from __future__ import annotations

from typing import Any

# Numeric features used by preprocessing
NUMERIC_FEATURES_V1: tuple[str, ...] = (
    "rainfall_rate_now_mm_h",
    "rainfall_accum_15m_mm",
    "rainfall_accum_30m_mm",
    "rainfall_accum_1h_mm",
    "rainfall_accum_3h_mm",
    "temperature_c",
    "humidity_pct",
    "wind_speed_mps",
    "weather_freshness_seconds",
    "water_depth_current_cm",
    "water_depth_trend_cm_per_min",
    "water_depth_max_30m_cm",
    "nearby_sensor_count",
    "sensor_confidence",
    "sensor_freshness_seconds",
    "length_m",
    "speed_limit_mps",
    "edge_elevation_m",
    "hour_of_day",
    "day_of_week",
    "month",
    "historical_flood_count_30d",
)

# Categorical features requiring one-hot encoding
CATEGORICAL_FEATURES_V1: tuple[str, ...] = (
    "road_class",
    "season_category",
)

# Boolean indicator and flag features
BOOLEAN_FEATURES_V1: tuple[str, ...] = (
    "is_bridge",
    "is_tunnel",
    "is_rainfall_missing",
    "is_water_depth_missing",
    "is_temperature_missing",
)

# Canonical ordered list of all model input features
MODEL_FEATURES_V1: tuple[str, ...] = (
    NUMERIC_FEATURES_V1 + CATEGORICAL_FEATURES_V1 + BOOLEAN_FEATURES_V1
)

# Explicitly excluded columns with rationales
EXCLUDED_COLUMNS_V1: dict[str, str] = {
    "edge_id": "Identifier memorization avoidance; spatial identifiers must not be direct features.",
    "observation_time": "Raw timestamp string; temporal information is captured by hour, day, month, season.",
    "prediction_horizon_minutes": "Metadata parameter (constant 30m in baseline training).",
    "source_type": "Constant across current dataset (all SYNTHETIC); zero discriminative value.",
    "dist_to_flood_zone_m": "Currently 100% missing; explicitly excluded to avoid ungrounded pseudo-signals.",
    "target_flooded_within_horizon": "Ground truth prediction target.",
}

FORBIDDEN_LEAKAGE_SUBSTRINGS: tuple[str, ...] = (
    "target",
    "future",
    "label",
    "ground_truth",
    "edge_id",
    "observation_time",
)


class FeatureLeakageAuditError(Exception):
    """Raised when forbidden leakage columns are detected in model input features."""


def audit_feature_leakage(feature_names: list[str] | tuple[str, ...]) -> None:
    """Audit feature list against forbidden leakage patterns.

    Raises FeatureLeakageAuditError if forbidden columns are found.
    """
    for name in feature_names:
        low = name.lower()
        for forbidden in FORBIDDEN_LEAKAGE_SUBSTRINGS:
            if forbidden in low:
                raise FeatureLeakageAuditError(
                    f"Leakage audit failed: forbidden pattern '{forbidden}' found in feature '{name}'."
                )
        if name in EXCLUDED_COLUMNS_V1:
            raise FeatureLeakageAuditError(
                f"Leakage audit failed: feature '{name}' is in the explicit exclusion list ({EXCLUDED_COLUMNS_V1[name]})."
            )


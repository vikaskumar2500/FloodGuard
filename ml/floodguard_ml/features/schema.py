"""Versioned feature schema definitions for FloodGuard ML datasets.

Schema Version: v1
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

FEATURE_VERSION = "v1"


@dataclass(frozen=True)
class FeatureColumn:
    name: str
    dtype: str  # "float64", "int64", "bool", "string"
    nullable: bool
    units: str
    description: str
    source: str  # "metadata", "weather", "sensor", "road", "temporal", "historical", "indicator", "target"
    availability_contract: str  # "<= T" or "T < t <= T + horizon"


FEATURE_COLUMNS_V1: tuple[FeatureColumn, ...] = (
    # Identification & Provenance metadata
    FeatureColumn("edge_id", "string", False, "uuid/id", "Road edge identifier", "metadata", "<= T"),
    FeatureColumn("observation_time", "string", False, "iso8601", "Observation timestamp T", "metadata", "<= T"),
    FeatureColumn("prediction_horizon_minutes", "int64", False, "minutes", "Prediction horizon H", "metadata", "<= T"),
    FeatureColumn("source_type", "string", False, "enum", "Data provenance (SYNTHETIC, REAL, MIXED)", "metadata", "<= T"),

    # Environmental & Weather features (<= T)
    FeatureColumn("rainfall_rate_now_mm_h", "float64", True, "mm/h", "Latest rainfall rate at or before T", "weather", "<= T"),
    FeatureColumn("rainfall_accum_15m_mm", "float64", True, "mm", "Total rainfall accumulated in (T - 15m, T]", "weather", "<= T"),
    FeatureColumn("rainfall_accum_30m_mm", "float64", True, "mm", "Total rainfall accumulated in (T - 30m, T]", "weather", "<= T"),
    FeatureColumn("rainfall_accum_1h_mm", "float64", True, "mm", "Total rainfall accumulated in (T - 1h, T]", "weather", "<= T"),
    FeatureColumn("rainfall_accum_3h_mm", "float64", True, "mm", "Total rainfall accumulated in (T - 3h, T]", "weather", "<= T"),
    FeatureColumn("temperature_c", "float64", True, "°C", "Air temperature at or before T", "weather", "<= T"),
    FeatureColumn("humidity_pct", "float64", True, "%", "Relative humidity 0–100% at or before T", "weather", "<= T"),
    FeatureColumn("wind_speed_mps", "float64", True, "m/s", "Wind speed at or before T", "weather", "<= T"),
    FeatureColumn("weather_freshness_seconds", "float64", True, "seconds", "Age of weather observation at T", "weather", "<= T"),

    # Sensor features (<= T)
    FeatureColumn("water_depth_current_cm", "float64", True, "cm", "Latest water depth reading at or before T", "sensor", "<= T"),
    FeatureColumn("water_depth_trend_cm_per_min", "float64", True, "cm/min", "Water depth rate of change from prior reading", "sensor", "<= T"),
    FeatureColumn("water_depth_max_30m_cm", "float64", True, "cm", "Maximum water depth in (T - 30m, T]", "sensor", "<= T"),
    FeatureColumn("nearby_sensor_count", "int64", False, "count", "Number of sensors associated with edge", "sensor", "<= T"),
    FeatureColumn("sensor_confidence", "float64", True, "score 0..1", "Quality confidence of latest sensor reading", "sensor", "<= T"),
    FeatureColumn("sensor_freshness_seconds", "float64", True, "seconds", "Age of sensor reading at T", "sensor", "<= T"),

    # Missingness Indicators (Preserving Missing != Zero)
    FeatureColumn("is_rainfall_missing", "bool", False, "boolean", "1 if rainfall was not observed/supplied, 0 if present (including 0.0)", "indicator", "<= T"),
    FeatureColumn("is_water_depth_missing", "bool", False, "boolean", "1 if sensor water depth was missing, 0 if present", "indicator", "<= T"),
    FeatureColumn("is_temperature_missing", "bool", False, "boolean", "1 if air temperature was missing, 0 if present", "indicator", "<= T"),

    # Road Topology features (<= T)
    FeatureColumn("road_class", "string", False, "category", "OSM road classification (primary, secondary, etc.)", "road", "<= T"),
    FeatureColumn("length_m", "float64", False, "meters", "Length of road segment in meters", "road", "<= T"),
    FeatureColumn("speed_limit_mps", "float64", True, "m/s", "Speed limit in meters per second", "road", "<= T"),
    FeatureColumn("is_bridge", "bool", False, "boolean", "Whether edge is on a bridge", "road", "<= T"),
    FeatureColumn("is_tunnel", "bool", False, "boolean", "Whether edge is in a tunnel", "road", "<= T"),
    FeatureColumn("edge_elevation_m", "float64", True, "meters", "Estimated elevation of edge centroid", "road", "<= T"),
    FeatureColumn("dist_to_flood_zone_m", "float64", True, "meters", "Distance to active flood zone boundary at T", "road", "<= T"),

    # Temporal features (<= T)
    FeatureColumn("hour_of_day", "int64", False, "0..23", "Hour of observation time", "temporal", "<= T"),
    FeatureColumn("day_of_week", "int64", False, "0..6", "Day of week (Monday=0)", "temporal", "<= T"),
    FeatureColumn("month", "int64", False, "1..12", "Month of observation time", "temporal", "<= T"),
    FeatureColumn("season_category", "string", False, "category", "Season classification (MONSOON, PRE_MONSOON, etc.)", "temporal", "<= T"),

    # Historical features (<= T)
    FeatureColumn("historical_flood_count_30d", "int64", False, "count", "Prior flood occurrences on this edge in preceding 30 days", "historical", "<= T"),

    # Prediction Target (Strictly from T < t <= T + horizon)
    FeatureColumn("target_flooded_within_horizon", "int64", False, "0 or 1", "Target: 1 if edge experiences HIGH/SEVERE flood in (T, T + horizon], else 0", "target", "T < t <= T + horizon"),
)


class FeatureSchemaV1:
    """Provides lookup and validation for FeatureSchemaV1."""

    version = FEATURE_VERSION
    columns = {col.name: col for col in FEATURE_COLUMNS_V1}
    feature_names = [col.name for col in FEATURE_COLUMNS_V1 if col.source not in {"metadata", "target"}]
    target_name = "target_flooded_within_horizon"
    metadata_names = [col.name for col in FEATURE_COLUMNS_V1 if col.source == "metadata"]

    @classmethod
    def to_dict(cls) -> list[dict[str, Any]]:
        return [asdict(col) for col in FEATURE_COLUMNS_V1]

    @classmethod
    def get_column(cls, name: str) -> FeatureColumn | None:
        return cls.columns.get(name)


FEATURE_SCHEMA_V1 = FeatureSchemaV1


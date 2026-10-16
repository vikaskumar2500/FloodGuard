"""Data quality validation and schema integrity checks."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

from floodguard_ml.features.schema import FEATURE_COLUMNS_V1, FeatureSchemaV1


class DatasetValidationError(Exception):
    """Raised when dataset fails critical schema or physical validity rules."""


@dataclass
class NumericFeatureStats:
    min_val: float | None
    max_val: float | None
    mean_val: float | None
    missing_count: int
    missing_pct: float


@dataclass
class QualityReport:
    total_rows: int
    duplicate_rows: int
    unique_edges: int
    min_time: str | None
    max_time: str | None
    positive_count: int
    negative_count: int
    positive_rate: float
    numeric_stats: dict[str, dict[str, Any]]
    categorical_stats: dict[str, dict[str, int]]
    missingness_by_feature: dict[str, float]


def validate_dataset(records: list[dict[str, Any]]) -> QualityReport:
    """Validate dataset rows against FeatureSchemaV1 and physical sanity rules.

    Raises DatasetValidationError on corrupt or unphysical data.
    Returns QualityReport on success.
    """
    if not records:
        raise DatasetValidationError("Dataset has 0 rows.")

    seen_keys: set[tuple[str, str, int]] = set()
    duplicate_count = 0
    unique_edges: set[str] = set()
    timestamps: list[str] = []

    pos_count = 0
    neg_count = 0

    # Initialize statistics accumulators
    numeric_cols = [c.name for c in FEATURE_COLUMNS_V1 if c.dtype == "float64"]
    cat_cols = [c.name for c in FEATURE_COLUMNS_V1 if c.dtype == "string" and c.name != "observation_time"]

    numeric_vals: dict[str, list[float]] = {c: [] for c in numeric_cols}
    missing_counts: dict[str, int] = {c.name: 0 for c in FEATURE_COLUMNS_V1}
    cat_distributions: dict[str, dict[str, int]] = {c: {} for c in cat_cols}

    for idx, row in enumerate(records):
        # 1. Row identity & duplicate check
        row_key = (row["edge_id"], row["observation_time"], row["prediction_horizon_minutes"])
        if row_key in seen_keys:
            duplicate_count += 1
        seen_keys.add(row_key)

        unique_edges.add(row["edge_id"])
        timestamps.append(row["observation_time"])

        # 2. Target check
        target = row.get("target_flooded_within_horizon")
        if target not in (0, 1):
            raise DatasetValidationError(f"Row {idx}: invalid target {target}, expected 0 or 1.")
        if target == 1:
            pos_count += 1
        else:
            neg_count += 1

        # 3. Required columns and physical checks
        for col in FEATURE_COLUMNS_V1:
            val = row.get(col.name)
            if val is None:
                if not col.nullable:
                    raise DatasetValidationError(f"Row {idx}: non-nullable column '{col.name}' is None.")
                missing_counts[col.name] += 1
                continue

            # Check infinity
            if isinstance(val, (int, float)):
                if math.isinf(val) or math.isnan(val):
                    raise DatasetValidationError(f"Row {idx}: column '{col.name}' contains NaN or Inf.")

            # Physical checks
            if col.name == "rainfall_rate_now_mm_h" and val < 0.0:
                raise DatasetValidationError(f"Row {idx}: negative rainfall rate {val}.")
            if col.name == "water_depth_current_cm" and val < 0.0:
                raise DatasetValidationError(f"Row {idx}: negative water depth {val}.")
            if col.name == "humidity_pct" and not (0.0 <= val <= 100.0):
                raise DatasetValidationError(f"Row {idx}: humidity out of bounds {val}.")
            if col.name == "wind_speed_mps" and val < 0.0:
                raise DatasetValidationError(f"Row {idx}: negative wind speed {val}.")

            if col.name in numeric_vals and isinstance(val, (int, float)):
                numeric_vals[col.name].append(float(val))

            if col.name in cat_distributions and isinstance(val, str):
                cat_distributions[col.name][val] = cat_distributions[col.name].get(val, 0) + 1

    total = len(records)
    if duplicate_count > 0:
        raise DatasetValidationError(f"Dataset contains {duplicate_count} duplicate rows.")

    # Calculate numeric stats
    numeric_stats: dict[str, dict[str, Any]] = {}
    for col_name, vals in numeric_vals.items():
        miss = missing_counts[col_name]
        miss_pct = round(miss / total, 4)
        if vals:
            mean = sum(vals) / len(vals)
            variance = sum((x - mean) ** 2 for x in vals) / len(vals)
            std = math.sqrt(variance)
            numeric_stats[col_name] = {
                "min": round(min(vals), 3),
                "max": round(max(vals), 3),
                "mean": round(mean, 3),
                "std": round(std, 3),
                "missing_count": miss,
                "missing_pct": miss_pct,
            }
        else:
            numeric_stats[col_name] = {
                "min": None,
                "max": None,
                "mean": None,
                "std": None,
                "missing_count": miss,
                "missing_pct": miss_pct,
            }

    missingness_pct = {
        col: round(cnt / total, 4) for col, cnt in missing_counts.items()
    }

    return QualityReport(
        total_rows=total,
        duplicate_rows=duplicate_count,
        unique_edges=len(unique_edges),
        min_time=min(timestamps) if timestamps else None,
        max_time=max(timestamps) if timestamps else None,
        positive_count=pos_count,
        negative_count=neg_count,
        positive_rate=round(pos_count / total, 4),
        numeric_stats=numeric_stats,
        categorical_stats=cat_distributions,
        missingness_by_feature=missingness_pct,
    )


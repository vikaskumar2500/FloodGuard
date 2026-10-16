"""Temporal and calendar feature computation."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def get_season_category(month: int) -> str:
    """Return explicit meteorological season for the Indian subcontinent / Mumbai climate.

    Mapping:
    - 6..9 (June–September): MONSOON
    - 10..11 (October–November): POST_MONSOON
    - 12, 1, 2 (December–February): DRY
    - 3..5 (March–May): PRE_MONSOON
    """
    if 6 <= month <= 9:
        return "MONSOON"
    if 10 <= month <= 11:
        return "POST_MONSOON"
    if month in (12, 1, 2):
        return "DRY"
    return "PRE_MONSOON"


def compute_temporal_features(dt: datetime) -> dict[str, Any]:
    """Compute deterministic calendar features for a given timestamp."""
    return {
        "hour_of_day": dt.hour,
        "day_of_week": dt.weekday(),
        "month": dt.month,
        "season_category": get_season_category(dt.month),
    }


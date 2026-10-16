"""Freshness assessment for environmental observations.

Freshness tiers:
    FRESH   — observed_at is within `fresh_seconds` of now
    STALE   — older than fresh_seconds but within `stale_seconds`
    EXPIRED — older than stale_seconds
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    EXPIRED = "EXPIRED"


def assess_freshness(
    observed_at: datetime,
    now: datetime | None = None,
    fresh_seconds: float = 600.0,  # 10 min
    stale_seconds: float = 3600.0,  # 1 hour
) -> FreshnessState:
    """Return the freshness tier for an observation.

    Args:
        observed_at: When the observation was recorded (must be timezone-aware).
        now: Reference time. Defaults to ``datetime.now(tz=timezone.utc)``.
        fresh_seconds: Age threshold below which data is FRESH.
        stale_seconds: Age threshold below which data is STALE (beyond = EXPIRED).

    Returns:
        FreshnessState enum member.
    """
    if now is None:
        now = datetime.now(tz=UTC)

    # Normalise both timestamps to UTC for comparison.
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    age_seconds = (now - observed_at).total_seconds()

    if age_seconds <= fresh_seconds:
        return FreshnessState.FRESH
    if age_seconds <= stale_seconds:
        return FreshnessState.STALE
    return FreshnessState.EXPIRED

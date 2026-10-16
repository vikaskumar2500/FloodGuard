from datetime import datetime, timedelta
from math import isfinite


def clamp01(value: float) -> float:
    if not isfinite(value):
        raise ValueError("risk measurements must be finite")
    return max(0.0, min(1.0, value))


def normalize_measurement(
    value: float | None, thresholds: tuple[float, float, float, float]
) -> float | None:
    if value is None:
        return None
    if not isfinite(value) or value < 0:
        raise ValueError("risk measurements must be finite and nonnegative")
    first, second, third, fourth = thresholds
    if value <= first:
        return value / first * 0.25
    if value <= second:
        return 0.25 + (value - first) / (second - first) * 0.25
    if value <= third:
        return 0.50 + (value - second) / (third - second) * 0.25
    if value <= fourth:
        return 0.75 + (value - third) / (fourth - third) * 0.25
    return 1.0


def freshness_weight(observed_at: datetime, now: datetime, validity: timedelta) -> float:
    if observed_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("risk timestamps must be timezone-aware")
    age = now - observed_at
    if age < timedelta(0) or age > validity:
        return 0.0
    return max(0.0, 1.0 - age / validity)


def age_seconds(observed_at: datetime, now: datetime) -> float | None:
    if observed_at.tzinfo is None or now.tzinfo is None:
        raise ValueError("risk timestamps must be timezone-aware")
    age = (now - observed_at).total_seconds()
    return age if age >= 0 else None

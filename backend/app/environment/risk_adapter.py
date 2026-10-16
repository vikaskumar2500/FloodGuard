"""Risk adapter — converts EnvironmentalObservation → WeatherEvidence.

This is the bridge between the environmental adapter layer (Phase 10) and the
existing Phase 6 risk engine.  It does NOT modify risk formulas.

Usage::

    evidence = observation_to_weather_evidence(obs)
    if evidence is not None:
        edge_evidence.weather.append(evidence)
"""

from __future__ import annotations

import logging

from app.environment.models import EnvironmentalObservation
from app.risk.models import WeatherEvidence

logger = logging.getLogger("floodguard.environment.risk_adapter")

# Open-Meteo returns hourly precipitation totals; we treat them as mm/h rates.
_DEFAULT_INTERVAL_MINUTES = 60


def observation_to_weather_evidence(
    obs: EnvironmentalObservation,
    observation_interval_minutes: int = _DEFAULT_INTERVAL_MINUTES,
) -> WeatherEvidence | None:
    """Convert an EnvironmentalObservation to a WeatherEvidence for the risk engine.

    If the observation has no rainfall information (``rainfall_mm_per_hour is None``),
    this function returns ``None`` — the caller should not inject absent data into
    the risk pipeline.

    Args:
        obs: Normalised environmental observation.
        observation_interval_minutes: Duration the rainfall value represents.

    Returns:
        WeatherEvidence instance, or None if rainfall is absent.
    """
    if obs.rainfall_mm_per_hour is None:
        # Provider did not supply rainfall — do not inject missing data.
        logger.debug(
            "observation_no_rainfall",
            extra={"provider": obs.provider, "external_id": obs.external_id},
        )
        return None

    return WeatherEvidence(
        rainfall_mm=obs.rainfall_mm_per_hour,
        observed_at=obs.observed_at,
        observation_interval_minutes=observation_interval_minutes,
    )

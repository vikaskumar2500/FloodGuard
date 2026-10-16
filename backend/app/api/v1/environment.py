"""GET /api/v1/environment/weather — current environmental observation endpoint.

Returns the normalized observation for the requested coordinates.
API keys are never included in the response.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.environment.freshness import assess_freshness
from app.environment.models import EnvironmentalObservation

logger = logging.getLogger("floodguard.api.environment")

router = APIRouter(prefix="/environment", tags=["environment"])


class WeatherResponse(BaseModel):
    """Public representation of an environmental observation.

    API keys and raw_metadata are intentionally excluded.
    """

    provider: str
    latitude: float
    longitude: float
    observed_at: str = Field(description="ISO-8601 UTC timestamp of the observation")
    rainfall_mm_per_hour: float | None = Field(
        description="Rainfall rate in mm/h. null means the provider did not supply this field."
    )
    temperature_c: float | None
    humidity_percent: float | None
    wind_speed_mps: float | None
    source_quality: str
    data_source_state: str = Field(
        description="How this observation was obtained: LIVE, CACHE_FRESH, CACHE_STALE, MOCK, UNAVAILABLE"
    )
    freshness: str = Field(description="FRESH, STALE, or EXPIRED based on observed_at age")


def _build_response(obs: EnvironmentalObservation) -> WeatherResponse:
    freshness = assess_freshness(obs.observed_at)
    return WeatherResponse(
        provider=obs.provider,
        latitude=obs.latitude,
        longitude=obs.longitude,
        observed_at=obs.observed_at.isoformat(),
        rainfall_mm_per_hour=obs.rainfall_mm_per_hour,
        temperature_c=obs.temperature_c,
        humidity_percent=obs.humidity_percent,
        wind_speed_mps=obs.wind_speed_mps,
        source_quality=obs.source_quality,
        data_source_state=obs.data_source_state.value,
        freshness=freshness.value,
    )


@router.get("/weather", response_model=WeatherResponse)
async def get_current_weather(
    request: Request,
    latitude: Annotated[float, Query(ge=-90.0, le=90.0, description="WGS-84 latitude")] = 19.0760,
    longitude: Annotated[
        float, Query(ge=-180.0, le=180.0, description="WGS-84 longitude")
    ] = 72.8777,
) -> WeatherResponse:
    """Return the current environmental observation for the given coordinates.

    Uses a cache-aside strategy:
    - LIVE: fresh data from provider
    - CACHE_FRESH: recent cached observation
    - CACHE_STALE: provider unavailable; returning older cached data
    - MOCK: deterministic mock data (no internet required)

    Response never includes API keys or raw provider metadata.
    """
    env_service = getattr(request.app.state, "environmental_service", None)
    if env_service is None:
        raise HTTPException(status_code=503, detail="Environmental service not available")

    try:
        obs = await env_service.get_current_weather(latitude, longitude)
        return _build_response(obs)
    except Exception as exc:
        logger.warning(
            "weather_endpoint_error",
            extra={"lat": latitude, "lon": longitude, "error": str(exc)},
        )
        raise HTTPException(status_code=503, detail="Weather data temporarily unavailable") from exc

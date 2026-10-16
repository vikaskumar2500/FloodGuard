"""EnvironmentalService — orchestrates provider, cache, normalization, and persistence.

Flow:
    1. Check Redis cache for a recent observation.
    2. On cache hit: return it with DataSourceState.CACHE_FRESH.
    3. On cache miss: call the provider.
    4. On provider success: cache the observation, return it with DataSourceState.LIVE.
    5. On provider failure with a stale cache entry: return stale entry with DataSourceState.CACHE_STALE.
    6. On provider failure with no usable cache: return a sentinel UNAVAILABLE observation or raise.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.environment.cache import EnvironmentalCache
from app.environment.exceptions import (
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.environment.freshness import FreshnessState, assess_freshness
from app.environment.models import DataSourceState, EnvironmentalObservation
from app.environment.providers.base import EnvironmentalProvider

if TYPE_CHECKING:
    pass

logger = logging.getLogger("floodguard.environment.service")


class EnvironmentalService:
    """Orchestrates provider calls, Redis caching, and freshness tracking.

    This service is the single entry-point for the rest of the application
    to obtain environmental observations.  The rest of the app should not
    talk to providers or the cache directly.

    Args:
        provider: The configured EnvironmentalProvider implementation.
        redis: An async Redis client, or None if Redis is unavailable.
        cache_ttl_seconds: How long to cache observations in Redis.
        freshness_fresh_seconds: Age threshold below which data is FRESH.
        freshness_stale_seconds: Age threshold below which data is STALE (beyond = EXPIRED).
    """

    def __init__(
        self,
        provider: EnvironmentalProvider,
        redis: Any | None = None,
        cache_ttl_seconds: int = 300,
        freshness_fresh_seconds: float = 600.0,
        freshness_stale_seconds: float = 3600.0,
    ) -> None:
        self._provider = provider
        self._cache = EnvironmentalCache(redis, ttl_seconds=cache_ttl_seconds)
        self._fresh_seconds = freshness_fresh_seconds
        self._stale_seconds = freshness_stale_seconds

    @property
    def provider(self) -> EnvironmentalProvider:
        return self._provider

    async def get_current_weather(
        self,
        lat: float,
        lon: float,
    ) -> EnvironmentalObservation:
        """Return the most current observation for (lat, lon).

        Cache-aside strategy:
            - Cache HIT within freshness window → return CACHE_FRESH.
            - Cache MISS or stale → call provider.
            - Provider success → update cache → return LIVE.
            - Provider failure + stale cache entry → return CACHE_STALE.
            - Provider failure + no cache → propagate exception.
        """
        now = datetime.now(tz=UTC)

        # 1. Check cache.
        cached = await self._cache.get(self._provider.provider_id, lat, lon)
        if cached is not None:
            freshness = assess_freshness(
                cached.observed_at,
                now=now,
                fresh_seconds=self._fresh_seconds,
                stale_seconds=self._stale_seconds,
            )
            if freshness in (FreshnessState.FRESH, FreshnessState.STALE):
                # Promote FRESH/STALE with appropriate state.
                state = (
                    DataSourceState.CACHE_FRESH
                    if freshness == FreshnessState.FRESH
                    else DataSourceState.CACHE_STALE
                )
                logger.debug(
                    "env_cache_used",
                    extra={
                        "provider": self._provider.provider_id,
                        "lat": lat,
                        "lon": lon,
                        "freshness": freshness.value,
                    },
                )
                # Return with corrected DataSourceState.
                return _with_state(cached, state)

        # 2. Call provider.
        try:
            obs = await self._provider.get_current_weather(lat, lon)
            await self._cache.set(obs)
            logger.info(
                "env_observation_received",
                extra={
                    "provider": obs.provider,
                    "lat": lat,
                    "lon": lon,
                    "rainfall": obs.rainfall_mm_per_hour,
                },
            )
            return obs
        except (ProviderUnavailable, ProviderTimeout, ProviderRateLimited) as exc:
            logger.warning(
                "env_provider_failed",
                extra={
                    "provider": self._provider.provider_id,
                    "error": str(exc),
                },
            )
            # 3. Stale cache fallback.
            if cached is not None:
                logger.info(
                    "env_using_stale_cache",
                    extra={"provider": self._provider.provider_id},
                )
                return _with_state(cached, DataSourceState.CACHE_STALE)
            raise


def _with_state(obs: EnvironmentalObservation, state: DataSourceState) -> EnvironmentalObservation:
    """Return a copy of `obs` with a different DataSourceState."""
    return EnvironmentalObservation(
        provider=obs.provider,
        external_id=obs.external_id,
        latitude=obs.latitude,
        longitude=obs.longitude,
        observed_at=obs.observed_at,
        received_at=obs.received_at,
        rainfall_mm_per_hour=obs.rainfall_mm_per_hour,
        temperature_c=obs.temperature_c,
        humidity_percent=obs.humidity_percent,
        wind_speed_mps=obs.wind_speed_mps,
        source_quality=obs.source_quality,
        data_source_state=state,
        raw_metadata=obs.raw_metadata,
    )

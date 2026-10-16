"""Environmental data Redis cache.

Cache key pattern:
    floodguard:v1:environment:{provider}:{lat_bucket}:{lon_bucket}

Where the location bucket is lat/lon rounded to 2 decimal places (~1.1 km grid).

Cache TTL is configured via settings.weather_cache_ttl_seconds.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.environment.models import DataSourceState, EnvironmentalObservation
from app.environment.normalization import location_bucket

logger = logging.getLogger("floodguard.environment.cache")

_ENV_KEY_PREFIX = "floodguard:v1:environment"


def _env_cache_key(provider: str, lat: float, lon: float) -> str:
    bucket = location_bucket(lat, lon)
    return f"{_ENV_KEY_PREFIX}:{provider}:{bucket}"


def _serialize_observation(obs: EnvironmentalObservation) -> str:
    """Serialize an observation to a JSON string for Redis storage."""
    data: dict[str, Any] = {
        "provider": obs.provider,
        "external_id": obs.external_id,
        "latitude": obs.latitude,
        "longitude": obs.longitude,
        "observed_at": obs.observed_at.isoformat(),
        "received_at": obs.received_at.isoformat(),
        "rainfall_mm_per_hour": obs.rainfall_mm_per_hour,  # None preserved
        "temperature_c": obs.temperature_c,
        "humidity_percent": obs.humidity_percent,
        "wind_speed_mps": obs.wind_speed_mps,
        "source_quality": obs.source_quality,
        # raw_metadata is not cached (may be large / not needed on retrieval)
    }
    return json.dumps(data)


def _deserialize_observation(
    raw: str, data_source_state: DataSourceState
) -> EnvironmentalObservation:
    """Deserialize a cached observation JSON string."""
    data = json.loads(raw)

    def _parse_dt(s: str) -> datetime:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt

    return EnvironmentalObservation(
        provider=data["provider"],
        external_id=data["external_id"],
        latitude=data["latitude"],
        longitude=data["longitude"],
        observed_at=_parse_dt(data["observed_at"]),
        received_at=_parse_dt(data["received_at"]),
        rainfall_mm_per_hour=data["rainfall_mm_per_hour"],  # None preserved as-is
        temperature_c=data["temperature_c"],
        humidity_percent=data["humidity_percent"],
        wind_speed_mps=data["wind_speed_mps"],
        source_quality=data["source_quality"],
        data_source_state=data_source_state,
        raw_metadata=None,
    )


class EnvironmentalCache:
    """Redis-backed cache for environmental observations.

    This is a pure cache layer — the authoritative source remains the provider.
    If Redis is unavailable the cache silently degrades; the service falls back
    to direct provider calls.
    """

    def __init__(self, redis: Any | None, ttl_seconds: int = 300) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, provider: str, lat: float, lon: float) -> EnvironmentalObservation | None:
        """Return a cached observation or None on miss / Redis unavailable."""
        if self._redis is None:
            return None
        key = _env_cache_key(provider, lat, lon)
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode()
            obs = _deserialize_observation(raw, DataSourceState.CACHE_FRESH)
            logger.debug("env_cache_hit", extra={"key": key})
            return obs
        except Exception:
            logger.warning("env_cache_get_error", extra={"key": key}, exc_info=True)
            return None

    async def set(self, obs: EnvironmentalObservation) -> None:
        """Store an observation. Silently ignores Redis errors."""
        if self._redis is None:
            return
        key = _env_cache_key(obs.provider, obs.latitude, obs.longitude)
        try:
            payload = _serialize_observation(obs)
            await self._redis.set(key, payload, ex=self._ttl)
            logger.debug("env_cache_set", extra={"key": key, "ttl": self._ttl})
        except Exception:
            logger.warning("env_cache_set_error", extra={"key": key}, exc_info=True)

    async def delete(self, provider: str, lat: float, lon: float) -> None:
        """Evict a cached entry."""
        if self._redis is None:
            return
        key = _env_cache_key(provider, lat, lon)
        try:
            await self._redis.delete(key)
        except Exception:
            logger.warning("env_cache_delete_error", extra={"key": key}, exc_info=True)

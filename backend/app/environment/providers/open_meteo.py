"""Open-Meteo environmental provider.

Open-Meteo (https://open-meteo.com/) is a free weather API that requires no
API key for basic usage, making it ideal for development and demos.

API used:
    GET https://api.open-meteo.com/v1/forecast
    ?latitude=<lat>&longitude=<lon>
    &current=precipitation,temperature_2m,relative_humidity_2m,wind_speed_10m
    &wind_speed_unit=ms

Response fields mapped:
    current.precipitation          → rainfall_mm_per_hour   (None if field absent)
    current.temperature_2m         → temperature_c          (None if field absent)
    current.relative_humidity_2m   → humidity_percent       (None if field absent)
    current.wind_speed_10m         → wind_speed_mps         (None if field absent)

Critical semantic rule preserved:
    API returns null field  → rainfall_mm_per_hour = None  (MISSING)
    API returns 0.0         → rainfall_mm_per_hour = 0.0   (ZERO RAIN)

Retry policy:
    - Max 3 attempts with exponential back-off + jitter.
    - Retried: connection errors, 5xx, 429.
    - Not retried: 401, 403, 404, other 4xx.
    - Sleep function is injectable for tests (no real sleeping in unit tests).
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from app.environment.exceptions import (
    ProviderAuthenticationError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.environment.models import DataSourceState, EnvironmentalObservation
from app.environment.providers.base import EnvironmentalProvider

logger = logging.getLogger("floodguard.environment.open_meteo")

_OPEN_METEO_BASE = "https://api.open-meteo.com"
_CURRENT_FIELDS = "precipitation,temperature_2m,relative_humidity_2m,wind_speed_10m"
_MAX_RETRIES = 3
_BASE_BACKOFF_S = 0.5
_MAX_BACKOFF_S = 10.0


def _jittered_backoff(attempt: int) -> float:
    """Return a jittered exponential back-off duration in seconds."""
    base = _BASE_BACKOFF_S * (2**attempt)
    capped = min(base, _MAX_BACKOFF_S)
    return capped * (0.5 + random.random() * 0.5)


class OpenMeteoProvider(EnvironmentalProvider):
    """Real-HTTP weather provider using the Open-Meteo public API.

    No API key is required for the free tier.  If ``api_key`` is supplied it
    will be passed as the ``apikey`` query parameter (Enterprise tier).

    Args:
        base_url: Override the API base URL (useful for test doubles).
        timeout_seconds: Per-request HTTP timeout.
        api_key: Optional API key (Enterprise tier; never logged or exposed).
        sleep_fn: Async sleep function (injectable for tests; defaults to asyncio.sleep).
    """

    def __init__(
        self,
        *,
        base_url: str = _OPEN_METEO_BASE,
        timeout_seconds: float = 5.0,
        api_key: str | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._api_key = api_key
        self._sleep = sleep_fn or asyncio.sleep

    @property
    def provider_id(self) -> str:
        return "open_meteo"

    @property
    def supports_rainfall(self) -> bool:
        return True

    @property
    def supports_forecast(self) -> bool:
        return False

    def _build_params(self, lat: float, lon: float) -> dict[str, Any]:
        params: dict[str, Any] = {
            "latitude": lat,
            "longitude": lon,
            "current": _CURRENT_FIELDS,
            "wind_speed_unit": "ms",
        }
        if self._api_key:
            params["apikey"] = self._api_key
        return params

    def _parse_response(
        self, data: dict[str, Any], lat: float, lon: float, received_at: datetime
    ) -> EnvironmentalObservation:
        """Parse the Open-Meteo JSON response into a normalised observation."""
        try:
            current: dict[str, Any] = data.get("current", {})
            time_str: str | None = current.get("time")
            if not time_str:
                raise ProviderInvalidResponse("open_meteo: missing current.time in response")

            # Parse observed_at — Open-Meteo returns ISO-8601 without timezone,
            # but their docs confirm it is UTC.
            try:
                observed_at = datetime.fromisoformat(time_str).replace(tzinfo=UTC)
            except ValueError as exc:
                raise ProviderInvalidResponse(
                    f"open_meteo: could not parse time '{time_str}'"
                ) from exc

            # CRITICAL: use dict.get with a sentinel to distinguish absent vs null.
            _MISSING = object()

            def _field(key: str) -> float | None:
                val = current.get(key, _MISSING)
                if val is _MISSING or val is None:
                    return None  # MISSING — never treated as zero
                return float(val)

            rainfall = _field("precipitation")
            temperature = _field("temperature_2m")
            humidity_raw = _field("relative_humidity_2m")
            wind = _field("wind_speed_10m")

            # Validate ranges — reject obviously corrupt data.
            if rainfall is not None and rainfall < 0:
                raise ProviderInvalidResponse(f"open_meteo: negative precipitation {rainfall}")
            if humidity_raw is not None and not (0.0 <= humidity_raw <= 100.0):
                raise ProviderInvalidResponse(f"open_meteo: humidity out of range {humidity_raw}")

            external_id = f"open_meteo:{round(lat, 4)}:{round(lon, 4)}:{observed_at.isoformat()}"

            return EnvironmentalObservation(
                provider="open_meteo",
                external_id=external_id,
                latitude=lat,
                longitude=lon,
                observed_at=observed_at,
                received_at=received_at,
                rainfall_mm_per_hour=rainfall,
                temperature_c=temperature,
                humidity_percent=humidity_raw,
                wind_speed_mps=wind,
                source_quality="good",
                data_source_state=DataSourceState.LIVE,
                raw_metadata=current,
            )
        except ProviderInvalidResponse:
            raise
        except Exception as exc:
            raise ProviderInvalidResponse(f"open_meteo: unexpected parse error: {exc}") from exc

    async def get_current_weather(
        self,
        lat: float,
        lon: float,
    ) -> EnvironmentalObservation:
        params = self._build_params(lat, lon)
        url = f"{self._base_url}/v1/forecast"
        received_at = datetime.now(tz=UTC)

        last_exc: Exception = ProviderUnavailable("open_meteo: no attempts made")
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(url, params=params)

                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception as exc:
                        raise ProviderInvalidResponse(f"open_meteo: invalid JSON: {exc}") from exc
                    return self._parse_response(data, lat, lon, received_at)

                if resp.status_code == 429:
                    retry_after: float | None = None
                    ra_header = resp.headers.get("Retry-After")
                    if ra_header:
                        try:
                            retry_after = float(ra_header)
                        except ValueError:
                            pass
                    last_exc = ProviderRateLimited(
                        "open_meteo: 429 rate limited", retry_after_seconds=retry_after
                    )
                    # Retry with back-off respecting Retry-After.
                    wait = retry_after if retry_after else _jittered_backoff(attempt)
                    logger.warning(
                        "open_meteo_rate_limited",
                        extra={"attempt": attempt, "wait_s": wait},
                    )
                    await self._sleep(wait)
                    continue

                if resp.status_code in {401, 403}:
                    raise ProviderAuthenticationError(
                        f"open_meteo: HTTP {resp.status_code} authentication error"
                    )

                if 500 <= resp.status_code < 600:
                    last_exc = ProviderUnavailable(f"open_meteo: server error {resp.status_code}")
                    await self._sleep(_jittered_backoff(attempt))
                    continue

                # Other 4xx: not retried.
                raise ProviderInvalidResponse(f"open_meteo: unexpected HTTP {resp.status_code}")

            except (ProviderAuthenticationError, ProviderInvalidResponse):
                raise
            except httpx.TimeoutException as exc:
                last_exc = ProviderTimeout(f"open_meteo: timeout on attempt {attempt}: {exc}")
                logger.warning("open_meteo_timeout", extra={"attempt": attempt})
                if attempt < _MAX_RETRIES - 1:
                    await self._sleep(_jittered_backoff(attempt))
                continue
            except httpx.RequestError as exc:
                last_exc = ProviderUnavailable(
                    f"open_meteo: request error on attempt {attempt}: {exc}"
                )
                logger.warning("open_meteo_request_error", extra={"attempt": attempt})
                if attempt < _MAX_RETRIES - 1:
                    await self._sleep(_jittered_backoff(attempt))
                continue

        raise last_exc

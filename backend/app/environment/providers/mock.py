"""Deterministic mock environmental provider for offline/test use.

The mock provider is fully configurable and supports:
- Static rainfall/temperature/humidity/wind values
- Simulated failure modes (force_failure, force_timeout)
- Stale observations (stale_hours > 0)
- Call counting for test assertions
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.environment.exceptions import ProviderTimeout, ProviderUnavailable
from app.environment.models import DataSourceState, EnvironmentalObservation
from app.environment.providers.base import EnvironmentalProvider

_MOCK_PROVIDER_ID = "mock"


class MockEnvironmentalProvider(EnvironmentalProvider):
    """Offline provider returning fully configurable deterministic observations.

    Designed for unit tests and local development without any internet access.

    Usage::

        provider = MockEnvironmentalProvider(rainfall_mm_per_hour=12.5)
        obs = await provider.get_current_weather(lat=19.0, lon=72.8)
        assert obs.rainfall_mm_per_hour == 12.5
        assert obs.data_source_state == DataSourceState.MOCK

    Force a failure::

        provider = MockEnvironmentalProvider(force_failure=True)
        with pytest.raises(ProviderUnavailable):
            await provider.get_current_weather(19.0, 72.8)
    """

    def __init__(
        self,
        *,
        # Core observation values (None = field not provided by this mock)
        rainfall_mm_per_hour: float | None = 0.0,
        temperature_c: float | None = 25.0,
        humidity_percent: float | None = 70.0,
        wind_speed_mps: float | None = 3.0,
        source_quality: str = "good",
        # Failure simulation
        force_failure: bool = False,
        force_timeout: bool = False,
        # Age simulation (positive = observation is `stale_hours` old)
        stale_hours: float = 0.0,
        # Clock injection for deterministic test timestamps
        fixed_now: datetime | None = None,
    ) -> None:
        self._rainfall = rainfall_mm_per_hour
        self._temperature = temperature_c
        self._humidity = humidity_percent
        self._wind = wind_speed_mps
        self._quality = source_quality
        self._force_failure = force_failure
        self._force_timeout = force_timeout
        self._stale_hours = stale_hours
        self._fixed_now = fixed_now
        self.call_count: int = 0

    @property
    def provider_id(self) -> str:
        return _MOCK_PROVIDER_ID

    @property
    def supports_rainfall(self) -> bool:
        return True

    @property
    def supports_forecast(self) -> bool:
        return False

    def _now(self) -> datetime:
        return self._fixed_now or datetime.now(tz=UTC)

    async def get_current_weather(
        self,
        lat: float,
        lon: float,
    ) -> EnvironmentalObservation:
        self.call_count += 1

        if self._force_failure:
            raise ProviderUnavailable("mock: forced failure")
        if self._force_timeout:
            raise ProviderTimeout("mock: forced timeout")

        now = self._now()
        observed_at = now - timedelta(hours=self._stale_hours)
        external_id = f"mock:{round(lat, 4)}:{round(lon, 4)}:{observed_at.isoformat()}"

        return EnvironmentalObservation(
            provider=_MOCK_PROVIDER_ID,
            external_id=external_id,
            latitude=lat,
            longitude=lon,
            observed_at=observed_at,
            received_at=now,
            rainfall_mm_per_hour=self._rainfall,
            temperature_c=self._temperature,
            humidity_percent=self._humidity,
            wind_speed_mps=self._wind,
            source_quality=self._quality,
            data_source_state=DataSourceState.MOCK,
            raw_metadata=None,
        )

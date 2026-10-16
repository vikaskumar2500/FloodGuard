"""EnvironmentalProvider abstract base class.

All providers must implement the async interface defined here.
Providers should only implement capabilities they genuinely support —
use the `supports_*` flags to advertise capability so callers can degrade
gracefully rather than receiving fake data.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.environment.models import EnvironmentalObservation


class EnvironmentalProvider(ABC):
    """Provider-agnostic interface for obtaining environmental observations.

    Implementors:
        MockEnvironmentalProvider — deterministic offline provider for tests.
        OpenMeteoProvider         — real HTTP provider using Open-Meteo API.
    """

    # --- Capability flags ------------------------------------------------
    @property
    def supports_rainfall(self) -> bool:
        """Whether this provider supplies rainfall data."""
        return True

    @property
    def supports_forecast(self) -> bool:
        """Whether this provider supports multi-hour forecasts."""
        return False

    @property
    def provider_id(self) -> str:
        """Short stable identifier used in cache keys and logs."""
        raise NotImplementedError

    # --- Core interface --------------------------------------------------
    @abstractmethod
    async def get_current_weather(
        self,
        lat: float,
        lon: float,
    ) -> EnvironmentalObservation:
        """Return the most current observation for the given coordinates.

        Args:
            lat: Latitude in WGS-84 decimal degrees.
            lon: Longitude in WGS-84 decimal degrees.

        Returns:
            A fully normalised EnvironmentalObservation.

        Raises:
            ProviderUnavailable: Network or DNS failure.
            ProviderTimeout: Request exceeded configured timeout.
            ProviderRateLimited: HTTP 429 received.
            ProviderAuthenticationError: HTTP 401/403 received.
            ProviderInvalidResponse: Response could not be parsed.
        """

    async def get_observations(
        self,
        lat: float,
        lon: float,
        radius_km: float = 10.0,
    ) -> list[EnvironmentalObservation]:
        """Return observations within `radius_km` of the given point.

        Default implementation returns a single-element list from
        ``get_current_weather``. Providers that support spatial queries
        may override this.
        """
        obs = await self.get_current_weather(lat, lon)
        return [obs]

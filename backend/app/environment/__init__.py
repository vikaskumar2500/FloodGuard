"""FloodGuard Phase 10 — Environmental Data Adapter Layer.

Provides a provider-agnostic interface for ingesting real weather
and rainfall observations into the Phase 6/8 risk pipeline.

Key components:
- EnvironmentalObservation: canonical normalized observation domain model
- EnvironmentalProvider ABC: pluggable provider interface
- MockEnvironmentalProvider: deterministic offline/test provider
- OpenMeteoProvider: real HTTP provider (Open-Meteo, no API key required)
- EnvironmentalService: orchestrates cache → provider → normalization
- EnvironmentalCache: Redis-backed observation cache
- EnvironmentalPollingService: background polling loop
- risk_adapter: converts observations to WeatherEvidence for the risk engine
"""

from .exceptions import (
    ProviderAuthenticationError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from .freshness import FreshnessState, assess_freshness
from .models import DataSourceState, EnvironmentalObservation
from .providers.base import EnvironmentalProvider
from .providers.mock import MockEnvironmentalProvider
from .providers.open_meteo import OpenMeteoProvider
from .risk_adapter import observation_to_weather_evidence
from .service import EnvironmentalService

__all__ = [
    "DataSourceState",
    "EnvironmentalObservation",
    "EnvironmentalProvider",
    "EnvironmentalService",
    "FreshnessState",
    "MockEnvironmentalProvider",
    "OpenMeteoProvider",
    "ProviderAuthenticationError",
    "ProviderInvalidResponse",
    "ProviderRateLimited",
    "ProviderTimeout",
    "ProviderUnavailable",
    "assess_freshness",
    "observation_to_weather_evidence",
]

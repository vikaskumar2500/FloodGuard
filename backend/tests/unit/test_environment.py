"""Phase 10 — Real Weather and Environmental Data Adapter Layer Unit Tests.

Covers:
- Domain model invariants (distinction of None vs 0.0 rainfall, range validations)
- Normalization utilities (speed, temperature, geographic cache bucketing)
- Freshness classification (FRESH / STALE / EXPIRED)
- Risk adapter bridge (observation to WeatherEvidence)
- Mock provider behavior (success, call counting, forced failure, forced timeout, simulated staleness)
- Open-Meteo HTTP provider (parsing, None vs 0.0, validation, retries, 429, 401, 500, timeouts)
- Redis environmental cache (cache-aside, TTL, None-preservation, graceful Redis error fallback)
- Environmental service orchestration (cache hit, cache miss, stale fallback on provider failure)
- Background polling service (material change detection, revision advance, event bus emission, clean stop)
- FastAPI /api/v1/environment/weather endpoint (200 OK, no secret leakage, 503 on error)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.environment.cache import EnvironmentalCache
from app.environment.exceptions import (
    ProviderAuthenticationError,
    ProviderInvalidResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.environment.freshness import FreshnessState, assess_freshness
from app.environment.models import DataSourceState, EnvironmentalObservation
from app.environment.normalization import (
    celsius_to_kelvin,
    kmh_to_mps,
    knots_to_mps,
    location_bucket,
    mps_to_kmh,
)
from app.environment.polling import EnvironmentalPollingService, _is_material
from app.environment.providers.mock import MockEnvironmentalProvider
from app.environment.providers.open_meteo import OpenMeteoProvider
from app.environment.risk_adapter import observation_to_weather_evidence
from app.environment.service import EnvironmentalService
from app.main import create_app
from app.realtime.coordinator import RuntimeRiskState
from app.realtime.event_bus import InMemoryEventBus
from tests.unit.test_cache import InMemoryFakeRedis

# ---------------------------------------------------------------------------
# 1. Normalization & Freshness Tests
# ---------------------------------------------------------------------------


class TestNormalizationAndFreshness:
    def test_unit_conversions(self) -> None:
        assert kmh_to_mps(36.0) == pytest.approx(10.0)
        assert mps_to_kmh(10.0) == pytest.approx(36.0)
        assert knots_to_mps(10.0) == pytest.approx(5.14444, rel=1e-3)
        assert celsius_to_kelvin(0.0) == pytest.approx(273.15)
        assert celsius_to_kelvin(25.0) == pytest.approx(298.15)

    def test_location_bucket(self) -> None:
        assert location_bucket(19.0760, 72.8777) == "19.08:72.88"
        assert location_bucket(19.0740, 72.8720) == "19.07:72.87"
        assert location_bucket(0.0, 0.0) == "0.0:0.0"

    def test_assess_freshness(self) -> None:
        now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

        # 5 minutes ago -> FRESH (threshold 10 min)
        obs_fresh = now - timedelta(minutes=5)
        assert assess_freshness(obs_fresh, now=now) == FreshnessState.FRESH

        # 30 minutes ago -> STALE (between 10 min and 60 min)
        obs_stale = now - timedelta(minutes=30)
        assert assess_freshness(obs_stale, now=now) == FreshnessState.STALE

        # 2 hours ago -> EXPIRED (beyond 60 min)
        obs_expired = now - timedelta(hours=2)
        assert assess_freshness(obs_expired, now=now) == FreshnessState.EXPIRED

    def test_assess_freshness_naive_timestamp_handled(self) -> None:
        now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
        obs_naive = datetime(2026, 10, 8, 11, 55, 0)  # naive, 5 min ago
        assert assess_freshness(obs_naive, now=now) == FreshnessState.FRESH


# ---------------------------------------------------------------------------
# 2. Domain Models & Critical Semantic Invariant Tests
# ---------------------------------------------------------------------------


class TestDomainModels:
    def test_distinguish_missing_vs_zero_rainfall(self) -> None:
        now = datetime.now(tz=UTC)

        obs_zero = EnvironmentalObservation(
            provider="mock",
            external_id="mock:0:0:now",
            latitude=19.0,
            longitude=72.8,
            observed_at=now,
            received_at=now,
            rainfall_mm_per_hour=0.0,  # Explicit ZERO
            temperature_c=25.0,
            humidity_percent=60.0,
            wind_speed_mps=2.0,
            source_quality="good",
            data_source_state=DataSourceState.MOCK,
        )

        obs_none = EnvironmentalObservation(
            provider="mock",
            external_id="mock:0:0:now2",
            latitude=19.0,
            longitude=72.8,
            observed_at=now,
            received_at=now,
            rainfall_mm_per_hour=None,  # MISSING
            temperature_c=25.0,
            humidity_percent=60.0,
            wind_speed_mps=2.0,
            source_quality="good",
            data_source_state=DataSourceState.MOCK,
        )

        assert obs_zero.rainfall_mm_per_hour == 0.0
        assert obs_zero.rainfall_mm_per_hour is not None
        assert obs_none.rainfall_mm_per_hour is None
        assert obs_none.rainfall_mm_per_hour != 0.0

    def test_validation_rejects_invalid_values(self) -> None:
        now = datetime.now(tz=UTC)

        # Negative rainfall
        with pytest.raises(ValueError, match="rainfall_mm_per_hour must be ≥ 0"):
            EnvironmentalObservation(
                provider="mock",
                external_id="test",
                latitude=0.0,
                longitude=0.0,
                observed_at=now,
                received_at=now,
                rainfall_mm_per_hour=-1.5,
                temperature_c=20.0,
                humidity_percent=50.0,
                wind_speed_mps=1.0,
                source_quality="good",
                data_source_state=DataSourceState.MOCK,
            )

        # Humidity > 100
        with pytest.raises(ValueError, match="humidity_percent must be 0–100"):
            EnvironmentalObservation(
                provider="mock",
                external_id="test",
                latitude=0.0,
                longitude=0.0,
                observed_at=now,
                received_at=now,
                rainfall_mm_per_hour=0.0,
                temperature_c=20.0,
                humidity_percent=105.0,
                wind_speed_mps=1.0,
                source_quality="good",
                data_source_state=DataSourceState.MOCK,
            )

        # Negative wind speed
        with pytest.raises(ValueError, match="wind_speed_mps must be ≥ 0"):
            EnvironmentalObservation(
                provider="mock",
                external_id="test",
                latitude=0.0,
                longitude=0.0,
                observed_at=now,
                received_at=now,
                rainfall_mm_per_hour=0.0,
                temperature_c=20.0,
                humidity_percent=50.0,
                wind_speed_mps=-5.0,
                source_quality="good",
                data_source_state=DataSourceState.MOCK,
            )


# ---------------------------------------------------------------------------
# 3. Risk Adapter Tests
# ---------------------------------------------------------------------------


class TestRiskAdapter:
    def test_observation_with_rainfall_creates_weather_evidence(self) -> None:
        now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
        obs = EnvironmentalObservation(
            provider="mock",
            external_id="test",
            latitude=19.0,
            longitude=72.8,
            observed_at=now,
            received_at=now,
            rainfall_mm_per_hour=15.5,
            temperature_c=28.0,
            humidity_percent=85.0,
            wind_speed_mps=4.5,
            source_quality="good",
            data_source_state=DataSourceState.LIVE,
        )

        evidence = observation_to_weather_evidence(obs, observation_interval_minutes=60)
        assert evidence is not None
        assert evidence.rainfall_mm == 15.5
        assert evidence.observed_at == now
        assert evidence.observation_interval_minutes == 60

    def test_observation_without_rainfall_returns_none(self) -> None:
        now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)
        obs = EnvironmentalObservation(
            provider="mock",
            external_id="test",
            latitude=19.0,
            longitude=72.8,
            observed_at=now,
            received_at=now,
            rainfall_mm_per_hour=None,  # Provider did not supply rainfall
            temperature_c=28.0,
            humidity_percent=85.0,
            wind_speed_mps=4.5,
            source_quality="good",
            data_source_state=DataSourceState.LIVE,
        )

        evidence = observation_to_weather_evidence(obs)
        assert evidence is None


# ---------------------------------------------------------------------------
# 4. Mock Environmental Provider Tests
# ---------------------------------------------------------------------------


class TestMockProvider:
    @pytest.mark.asyncio
    async def test_mock_provider_defaults_and_counting(self) -> None:
        provider = MockEnvironmentalProvider()
        assert provider.provider_id == "mock"
        assert provider.supports_rainfall is True
        assert provider.call_count == 0

        obs = await provider.get_current_weather(19.076, 72.877)
        assert provider.call_count == 1
        assert obs.provider == "mock"
        assert obs.rainfall_mm_per_hour == 0.0
        assert obs.data_source_state == DataSourceState.MOCK

    @pytest.mark.asyncio
    async def test_mock_provider_configurable_values(self) -> None:
        provider = MockEnvironmentalProvider(
            rainfall_mm_per_hour=22.5,
            temperature_c=31.0,
            humidity_percent=92.0,
            wind_speed_mps=6.5,
        )
        obs = await provider.get_current_weather(19.0, 72.8)
        assert obs.rainfall_mm_per_hour == 22.5
        assert obs.temperature_c == 31.0
        assert obs.humidity_percent == 92.0
        assert obs.wind_speed_mps == 6.5

    @pytest.mark.asyncio
    async def test_mock_provider_stale_simulation(self) -> None:
        fixed_now = datetime(2026, 10, 8, 14, 0, 0, tzinfo=UTC)
        provider = MockEnvironmentalProvider(stale_hours=3.0, fixed_now=fixed_now)
        obs = await provider.get_current_weather(19.0, 72.8)

        expected_observed = fixed_now - timedelta(hours=3)
        assert obs.observed_at == expected_observed
        assert obs.received_at == fixed_now

    @pytest.mark.asyncio
    async def test_mock_provider_failure_modes(self) -> None:
        p_fail = MockEnvironmentalProvider(force_failure=True)
        with pytest.raises(ProviderUnavailable, match="forced failure"):
            await p_fail.get_current_weather(19.0, 72.8)

        p_timeout = MockEnvironmentalProvider(force_timeout=True)
        with pytest.raises(ProviderTimeout, match="forced timeout"):
            await p_timeout.get_current_weather(19.0, 72.8)


# ---------------------------------------------------------------------------
# 5. Open-Meteo Real HTTP Provider Tests
# ---------------------------------------------------------------------------


class TestOpenMeteoProvider:
    @pytest.mark.asyncio
    async def test_parse_valid_response(self) -> None:
        fake_json = {
            "latitude": 19.076,
            "longitude": 72.877,
            "current": {
                "time": "2026-10-08T12:00",
                "precipitation": 14.2,
                "temperature_2m": 29.5,
                "relative_humidity_2m": 80.0,
                "wind_speed_10m": 4.1,
            },
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_json

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            provider = OpenMeteoProvider()
            obs = await provider.get_current_weather(19.076, 72.877)

            assert obs.provider == "open_meteo"
            assert obs.rainfall_mm_per_hour == 14.2
            assert obs.temperature_c == 29.5
            assert obs.humidity_percent == 80.0
            assert obs.wind_speed_mps == 4.1
            assert obs.data_source_state == DataSourceState.LIVE

    @pytest.mark.asyncio
    async def test_null_precipitation_maps_to_none_not_zero(self) -> None:
        fake_json = {
            "current": {
                "time": "2026-10-08T12:00",
                "precipitation": None,  # Provider did not supply precipitation
                "temperature_2m": 25.0,
                "relative_humidity_2m": 50.0,
                "wind_speed_10m": 2.0,
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_json

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            provider = OpenMeteoProvider()
            obs = await provider.get_current_weather(19.0, 72.8)

            assert obs.rainfall_mm_per_hour is None
            assert obs.rainfall_mm_per_hour != 0.0

    @pytest.mark.asyncio
    async def test_zero_precipitation_maps_to_explicit_zero(self) -> None:
        fake_json = {
            "current": {
                "time": "2026-10-08T12:00",
                "precipitation": 0.0,  # Explicit ZERO
                "temperature_2m": 25.0,
                "relative_humidity_2m": 50.0,
                "wind_speed_10m": 2.0,
            }
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = fake_json

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            provider = OpenMeteoProvider()
            obs = await provider.get_current_weather(19.0, 72.8)

            assert obs.rainfall_mm_per_hour == 0.0
            assert obs.rainfall_mm_per_hour is not None

    @pytest.mark.asyncio
    async def test_rejects_corrupted_payloads(self) -> None:
        # Negative precipitation
        bad_rain = {
            "current": {
                "time": "2026-10-08T12:00",
                "precipitation": -5.0,
                "temperature_2m": 20.0,
                "relative_humidity_2m": 50.0,
                "wind_speed_10m": 1.0,
            }
        }
        mock_resp = MagicMock(status_code=200, json=MagicMock(return_value=bad_rain))
        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            with pytest.raises(ProviderInvalidResponse, match="negative precipitation"):
                await OpenMeteoProvider().get_current_weather(19.0, 72.8)

        # Humidity > 100
        bad_hum = {
            "current": {
                "time": "2026-10-08T12:00",
                "precipitation": 0.0,
                "temperature_2m": 20.0,
                "relative_humidity_2m": 120.0,
                "wind_speed_10m": 1.0,
            }
        }
        mock_resp.json.return_value = bad_hum
        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            with pytest.raises(ProviderInvalidResponse, match="humidity out of range"):
                await OpenMeteoProvider().get_current_weather(19.0, 72.8)

    @pytest.mark.asyncio
    async def test_auth_error_not_retried(self) -> None:
        mock_resp = MagicMock(status_code=401)
        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            provider = OpenMeteoProvider()
            with pytest.raises(ProviderAuthenticationError):
                await provider.get_current_weather(19.0, 72.8)

    @pytest.mark.asyncio
    async def test_rate_limited_retries_with_backoff(self) -> None:
        mock_resp = MagicMock(status_code=429, headers={"Retry-After": "0.01"})
        sleep_mock = AsyncMock()

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            provider = OpenMeteoProvider(sleep_fn=sleep_mock)
            with pytest.raises(ProviderRateLimited) as exc_info:
                await provider.get_current_weather(19.0, 72.8)

            assert exc_info.value.retry_after_seconds == 0.01
            # Should have attempted 3 times, retrying twice with sleep
            assert sleep_mock.call_count == 3

    @pytest.mark.asyncio
    async def test_server_error_retries_exhausted(self) -> None:
        mock_resp = MagicMock(status_code=503)
        sleep_mock = AsyncMock()

        with patch("httpx.AsyncClient.get", return_value=mock_resp):
            provider = OpenMeteoProvider(sleep_fn=sleep_mock)
            with pytest.raises(ProviderUnavailable, match="server error 503"):
                await provider.get_current_weather(19.0, 72.8)

            assert sleep_mock.call_count == 3

    @pytest.mark.asyncio
    async def test_timeout_retries_exhausted(self) -> None:
        sleep_mock = AsyncMock()
        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("slow")):
            provider = OpenMeteoProvider(sleep_fn=sleep_mock)
            with pytest.raises(ProviderTimeout):
                await provider.get_current_weather(19.0, 72.8)

            assert sleep_mock.call_count == 2  # sleep between attempts 0-1 and 1-2


# ---------------------------------------------------------------------------
# 6. Environmental Redis Cache Tests
# ---------------------------------------------------------------------------


class TestEnvironmentalCache:
    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self) -> None:
        fake_redis = InMemoryFakeRedis()
        cache = EnvironmentalCache(fake_redis, ttl_seconds=300)

        res = await cache.get("open_meteo", 19.0, 72.8)
        assert res is None

    @pytest.mark.asyncio
    async def test_cache_set_and_get(self) -> None:
        fake_redis = InMemoryFakeRedis()
        cache = EnvironmentalCache(fake_redis, ttl_seconds=300)
        now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

        obs = EnvironmentalObservation(
            provider="open_meteo",
            external_id="om:1",
            latitude=19.076,
            longitude=72.877,
            observed_at=now,
            received_at=now,
            rainfall_mm_per_hour=8.5,
            temperature_c=27.0,
            humidity_percent=75.0,
            wind_speed_mps=3.2,
            source_quality="good",
            data_source_state=DataSourceState.LIVE,
        )

        await cache.set(obs)
        cached = await cache.get("open_meteo", 19.076, 72.877)

        assert cached is not None
        assert cached.provider == "open_meteo"
        assert cached.rainfall_mm_per_hour == 8.5
        assert cached.data_source_state == DataSourceState.CACHE_FRESH

    @pytest.mark.asyncio
    async def test_cache_preserves_none_rainfall(self) -> None:
        fake_redis = InMemoryFakeRedis()
        cache = EnvironmentalCache(fake_redis, ttl_seconds=300)
        now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

        obs = EnvironmentalObservation(
            provider="open_meteo",
            external_id="om:2",
            latitude=19.0,
            longitude=72.8,
            observed_at=now,
            received_at=now,
            rainfall_mm_per_hour=None,  # MISSING
            temperature_c=25.0,
            humidity_percent=50.0,
            wind_speed_mps=1.0,
            source_quality="good",
            data_source_state=DataSourceState.LIVE,
        )

        await cache.set(obs)
        cached = await cache.get("open_meteo", 19.0, 72.8)
        assert cached is not None
        assert cached.rainfall_mm_per_hour is None

    @pytest.mark.asyncio
    async def test_cache_delete(self) -> None:
        fake_redis = InMemoryFakeRedis()
        cache = EnvironmentalCache(fake_redis, ttl_seconds=300)
        now = datetime.now(tz=UTC)

        obs = EnvironmentalObservation(
            provider="mock",
            external_id="m:1",
            latitude=19.0,
            longitude=72.8,
            observed_at=now,
            received_at=now,
            rainfall_mm_per_hour=0.0,
            temperature_c=20.0,
            humidity_percent=50.0,
            wind_speed_mps=1.0,
            source_quality="good",
            data_source_state=DataSourceState.MOCK,
        )

        await cache.set(obs)
        assert await cache.get("mock", 19.0, 72.8) is not None

        await cache.delete("mock", 19.0, 72.8)
        assert await cache.get("mock", 19.0, 72.8) is None

    @pytest.mark.asyncio
    async def test_cache_degrades_gracefully_on_redis_error(self) -> None:
        fake_redis = InMemoryFakeRedis()
        fake_redis.error_on_get = True
        fake_redis.error_on_set = True
        cache = EnvironmentalCache(fake_redis, ttl_seconds=300)

        # Should not raise exception
        res = await cache.get("mock", 19.0, 72.8)
        assert res is None


# ---------------------------------------------------------------------------
# 7. Environmental Service Orchestration Tests
# ---------------------------------------------------------------------------


class TestEnvironmentalService:
    @pytest.mark.asyncio
    async def test_cache_miss_calls_provider_and_populates_cache(self) -> None:
        fake_redis = InMemoryFakeRedis()
        mock_provider = MockEnvironmentalProvider(rainfall_mm_per_hour=11.0)
        service = EnvironmentalService(mock_provider, redis=fake_redis, cache_ttl_seconds=300)

        obs = await service.get_current_weather(19.0, 72.8)
        assert obs.rainfall_mm_per_hour == 11.0
        assert mock_provider.call_count == 1

        # Second call should hit cache; provider call count stays 1
        obs2 = await service.get_current_weather(19.0, 72.8)
        assert obs2.rainfall_mm_per_hour == 11.0
        assert obs2.data_source_state == DataSourceState.CACHE_FRESH
        assert mock_provider.call_count == 1

    @pytest.mark.asyncio
    async def test_provider_failure_falls_back_to_stale_cache(self) -> None:
        fake_redis = InMemoryFakeRedis()
        mock_provider = MockEnvironmentalProvider(rainfall_mm_per_hour=5.0)
        service = EnvironmentalService(mock_provider, redis=fake_redis, cache_ttl_seconds=300)

        # Initial successful call populates cache
        obs1 = await service.get_current_weather(19.0, 72.8)
        assert obs1.data_source_state == DataSourceState.MOCK

        # Now provider fails
        mock_provider._force_failure = True

        # Service should fall back to cached data with CACHE_STALE or CACHE_FRESH
        obs_fallback = await service.get_current_weather(19.0, 72.8)
        assert obs_fallback.rainfall_mm_per_hour == 5.0
        assert obs_fallback.data_source_state in {
            DataSourceState.CACHE_FRESH,
            DataSourceState.CACHE_STALE,
        }

    @pytest.mark.asyncio
    async def test_provider_failure_with_no_cache_propagates_error(self) -> None:
        mock_provider = MockEnvironmentalProvider(force_failure=True)
        service = EnvironmentalService(mock_provider, redis=None)

        with pytest.raises(ProviderUnavailable):
            await service.get_current_weather(19.0, 72.8)


# ---------------------------------------------------------------------------
# 8. Background Polling Service Tests
# ---------------------------------------------------------------------------


class TestPollingService:
    @pytest.mark.asyncio
    async def test_materiality_threshold(self) -> None:
        assert _is_material(current=1.0, previous=None) is True
        assert _is_material(current=0.0, previous=None) is False
        assert _is_material(current=None, previous=1.0) is False
        # Below 0.5 mm/h threshold: not material
        assert _is_material(current=5.2, previous=5.0) is False
        # Above 0.5 mm/h threshold: material
        assert _is_material(current=6.0, previous=5.0) is True

    @pytest.mark.asyncio
    async def test_polling_material_change_advances_risk_revision(self) -> None:
        provider = MockEnvironmentalProvider(rainfall_mm_per_hour=0.0)
        service = EnvironmentalService(provider, redis=None)
        risk_state = RuntimeRiskState(threshold=0.1)
        event_bus = InMemoryEventBus()

        received_events: list[dict] = []
        event_bus.subscribe("risk.edges_changed", lambda ev: received_events.append(ev))

        poller = EnvironmentalPollingService(
            env_service=service,
            runtime_risk_state=risk_state,
            locations=[(19.0, 72.8)],
            interval_seconds=10.0,
            target_edge_ids=["edge-A-B"],
            event_bus=event_bus,
        )

        # 1. First poll with 0 rainfall: not material (0 rain from none is ignored)
        await poller.poll_once()
        assert risk_state.revision == 0
        assert len(received_events) == 0

        # 2. Update provider to material rainfall (e.g. 15 mm/h)
        provider._rainfall = 15.0
        await poller.poll_once()
        assert risk_state.revision == 1
        assert len(received_events) == 1
        assert received_events[0]["riskRevision"] == 1
        assert "edge-A-B" in received_events[0]["edgeIds"]

        # 3. Same observation: does not advance revision again
        await poller.poll_once()
        assert risk_state.revision == 1
        assert len(received_events) == 1

    @pytest.mark.asyncio
    async def test_polling_lifecycle_clean_stop(self) -> None:
        provider = MockEnvironmentalProvider()
        service = EnvironmentalService(provider, redis=None)
        poller = EnvironmentalPollingService(
            env_service=service,
            locations=[(19.0, 72.8)],
            interval_seconds=3600.0,  # long interval
        )

        assert not poller.is_running
        await poller.start()
        assert poller.is_running

        await poller.stop()
        assert not poller.is_running


# ---------------------------------------------------------------------------
# 9. FastAPI Weather Endpoint Tests
# ---------------------------------------------------------------------------


class TestWeatherApi:
    @pytest.fixture
    def client(self) -> TestClient:
        settings = Settings(
            app_env="test",
            use_fixture_routing=True,
            environment_provider="mock",
            cache_enabled=False,
            weather_polling_enabled=False,
        )
        app = create_app(settings)
        with TestClient(app) as test_client:
            yield test_client

    def test_get_current_weather_endpoint_success(self, client: TestClient) -> None:
        resp = client.get("/api/v1/environment/weather?latitude=19.0760&longitude=72.8777")
        assert resp.status_code == 200
        data = resp.json()

        assert data["provider"] == "mock"
        assert data["latitude"] == pytest.approx(19.0760)
        assert data["longitude"] == pytest.approx(72.8777)
        assert "observed_at" in data
        assert "rainfall_mm_per_hour" in data
        assert "temperature_c" in data
        assert "freshness" in data
        assert data["data_source_state"] == "MOCK"

        # Ensure NO secrets or raw debug dicts leaked
        assert "apikey" not in data
        assert "api_key" not in data
        assert "raw_metadata" not in data

    def test_get_current_weather_endpoint_provider_error(self) -> None:
        settings = Settings(
            app_env="test",
            use_fixture_routing=True,
            environment_provider="mock",
            cache_enabled=False,
            weather_polling_enabled=False,
        )
        app = create_app(settings)

        # Force mock provider in app.state to fail
        with TestClient(app) as client:
            app.state.environmental_service.provider._force_failure = True
            resp = client.get("/api/v1/environment/weather?latitude=19.0&longitude=72.8")
            assert resp.status_code == 503
            assert resp.json()["type"] == "SERVICE_UNAVAILABLE" or "detail" in resp.json()

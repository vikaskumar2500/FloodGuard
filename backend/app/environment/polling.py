"""Background polling service for environmental observations.

Polls one or more configured locations at a fixed interval and applies
any material rainfall changes to ``RuntimeRiskState``.

This service is:
- Disabled by default (``weather_polling_enabled=False``).
- Started in the application lifespan only when explicitly enabled.
- Stopped cleanly on application shutdown.

Integration with risk pipeline:
    Each polled observation is converted to ``WeatherEvidence`` via the
    risk adapter.  The observation is then checked for materiality before
    updating ``RuntimeRiskState`` to avoid churning risk revisions on every
    heartbeat.

Materiality rule:
    An observation is material if ``rainfall_mm_per_hour`` is not None and
    differs from the last known value for that location by more than
    ``RAINFALL_CHANGE_THRESHOLD_MM_H``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.environment.risk_adapter import observation_to_weather_evidence
from app.environment.service import EnvironmentalService

if TYPE_CHECKING:
    from app.realtime.coordinator import RuntimeRiskState

logger = logging.getLogger("floodguard.environment.polling")

# Minimum change in mm/h that counts as material and triggers a risk revision.
RAINFALL_CHANGE_THRESHOLD_MM_H = 0.5


@dataclass
class _LocationState:
    """Tracks the last known rainfall value for a polled location."""

    lat: float
    lon: float
    last_rainfall: float | None = field(default=None)


class EnvironmentalPollingService:
    """Periodic poller that feeds environmental observations into the risk pipeline.

    Args:
        env_service: The EnvironmentalService to query.
        runtime_risk_state: The RuntimeRiskState to update with new evidence (optional).
        locations: List of (lat, lon) tuples to poll on each tick.
        interval_seconds: How often to poll each location.
        target_edge_ids: Explicit edge IDs to update on material weather changes.
        event_bus: Optional event bus to publish risk.edges_changed events.
        sleep_fn: Async sleep function (injectable for tests).
    """

    def __init__(
        self,
        env_service: EnvironmentalService,
        runtime_risk_state: RuntimeRiskState | None = None,
        locations: list[tuple[float, float]] | None = None,
        interval_seconds: float = 300.0,
        target_edge_ids: list[str] | None = None,
        event_bus: Any | None = None,
        event_publisher: Any | None = None,
        sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._env_service = env_service
        self._risk_state = runtime_risk_state
        self._locations = [_LocationState(lat, lon) for lat, lon in (locations or [])]
        self._interval = interval_seconds
        self._target_edge_ids = list(target_edge_ids) if target_edge_ids else []
        self._event_bus = event_bus
        self._event_publisher = event_publisher
        self._sleep = sleep_fn or asyncio.sleep
        self._task: asyncio.Task | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Start the polling loop in the background."""
        if self._task is not None and not self._task.done():
            logger.warning("polling_already_running")
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="env_polling")
        logger.info(
            "env_polling_started",
            extra={"interval_s": self._interval, "locations": len(self._locations)},
        )

    async def stop(self) -> None:
        """Stop the polling loop gracefully."""
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("env_polling_stopped")

    async def poll_once(self) -> None:
        """Run a single polling cycle synchronously (useful for tests and on-demand sync)."""
        await self._poll_all()

    async def _loop(self) -> None:
        while self._running:
            await self._poll_all()
            try:
                await self._sleep(self._interval)
            except asyncio.CancelledError:
                break

    async def _poll_all(self) -> None:
        for location_state in self._locations:
            try:
                await self._poll_location(location_state)
            except Exception:
                logger.warning(
                    "env_poll_error",
                    extra={"lat": location_state.lat, "lon": location_state.lon},
                    exc_info=True,
                )

    async def _poll_location(self, location_state: _LocationState) -> None:
        obs = await self._env_service.get_current_weather(location_state.lat, location_state.lon)

        evidence = observation_to_weather_evidence(obs)
        if evidence is None:
            # No rainfall data — nothing to apply.
            return

        rainfall = obs.rainfall_mm_per_hour
        last = location_state.last_rainfall

        if not _is_material(rainfall, last):
            logger.debug(
                "env_poll_not_material",
                extra={
                    "lat": location_state.lat,
                    "lon": location_state.lon,
                    "rainfall": rainfall,
                    "last_rainfall": last,
                },
            )
            return

        # Advance revision when material change is detected.
        # Use synthetic event_id based on the observation's external_id to guarantee idempotency.
        event_id = f"env_poll:{obs.external_id}"
        edges = self._target_edge_ids or [
            f"env_edge_{round(location_state.lat, 2)}_{round(location_state.lon, 2)}"
        ]
        score = min(1.0, max(0.0, rainfall / 30.0))
        level = (
            "SEVERE"
            if score >= 0.75
            else ("HIGH" if score >= 0.5 else ("MODERATE" if score >= 0.25 else "LOW"))
        )
        is_severe = level == "SEVERE"
        changes = {edge_id: (score, level, is_severe) for edge_id in edges}

        material_edges: set[str] = set()
        new_rev: int | None = None
        if self._risk_state is not None and self._event_publisher is None:
            new_rev, material_edges = self._risk_state.apply(event_id, changes)

        if self._event_publisher is not None:
            from app.messaging.models import create_weather_observed_event

            wev = create_weather_observed_event(
                latitude=location_state.lat,
                longitude=location_state.lon,
                rainfall_rate_mm_h=rainfall,
                temperature_c=obs.temperature_c,
                observation_time=obs.observed_at,
                road_edge_ids=edges,
                producer="environment.polling_service",
                event_id=event_id,
            )
            try:
                result = await self._event_publisher.publish(wev)
                if not result.success:
                    logger.warning("weather_event_publish_failed", extra={"event_id": event_id})
                    return
            except Exception as err:
                logger.warning("Failed to publish weather observation event: %s", err)
                return

        location_state.last_rainfall = rainfall
        logger.info(
            "env_poll_material_change",
            extra={
                "lat": location_state.lat,
                "lon": location_state.lon,
                "rainfall": rainfall,
                "previous": last,
                "revision": new_rev,
                "material_edges": list(material_edges),
            },
        )

        if material_edges and self._event_bus is not None and new_rev is not None:
            await self._event_bus.publish_async(
                {
                    "eventType": "risk.edges_changed",
                    "riskRevision": new_rev,
                    "edgeIds": sorted(material_edges),
                    "sourceEventId": event_id,
                }
            )


def _is_material(current: float | None, previous: float | None) -> bool:
    """Return True if the rainfall change is large enough to warrant a risk revision."""
    if current is None:
        return False
    if previous is None:
        # First observation — always material if non-zero.
        return current > 0.0
    return abs(current - previous) >= RAINFALL_CHANGE_THRESHOLD_MM_H

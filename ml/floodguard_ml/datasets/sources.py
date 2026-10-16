"""Data source adapters for ML dataset generation.

Supports:
- SimulationSource: Phase 7 simulation scenarios (SYNTHETIC)
- DatabaseSource: PostgreSQL/PostGIS repository tables (REAL)

Strict provenance contract:
Every source marks its output as SYNTHETIC or REAL.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from floodguard_ml.features.rainfall import WeatherRecord
from floodguard_ml.features.road import RoadEdgeAttributes
from floodguard_ml.features.sensors import SensorRecord
from floodguard_ml.labels.flood_labels import GroundTruthEvent


@dataclass
class SourceBundle:
    """Consolidated raw inputs for dataset builder."""

    source_type: str  # "SYNTHETIC", "REAL", "MIXED"
    source_identifiers: list[str]
    roads: dict[str, RoadEdgeAttributes]
    weather_by_edge: dict[str, list[WeatherRecord]] = field(default_factory=dict)
    sensors_by_edge: dict[str, list[SensorRecord]] = field(default_factory=dict)
    ground_truth_by_edge: dict[str, list[GroundTruthEvent]] = field(default_factory=dict)
    past_flood_events: dict[str, list[datetime]] = field(default_factory=dict)
    min_time: datetime | None = None
    max_time: datetime | None = None


class DataSourceAdapter(ABC):
    """Abstract interface for dataset source ingestion."""

    @abstractmethod
    def load_data(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> SourceBundle:
        """Load and return structured data bundle."""


class SimulationSource(DataSourceAdapter):
    """Generates source data from deterministic Phase 7 simulator scenarios.

    Provenance is strictly marked as SYNTHETIC.
    """

    def __init__(
        self,
        scenarios: tuple[str, ...] = ("NORMAL", "MODERATE_RAIN", "SEVERE_RAIN", "FLASH_FLOOD", "RECOVERY"),
        seed: int = 42,
        base_time: datetime | None = None,
    ) -> None:
        self.scenarios = scenarios
        self.seed = seed
        self.base_time = base_time or datetime(2026, 10, 7, 0, 0, tzinfo=timezone.utc)

    def load_data(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> SourceBundle:
        import sys
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[3]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        from simulations.clock import SimulationClock
        from simulations.engine import generate_events, seeded_scenario
        from simulations.models import EventType

        # Road edges from FloodGuard corridor fixture
        roads = {
            "fixture-top-1": RoadEdgeAttributes("fixture-top-1", "primary", 100.0, 13.88, False, False, 10.0),
            "fixture-top-2": RoadEdgeAttributes("fixture-top-2", "primary", 100.0, 13.88, False, False, 8.0),
            "fixture-top-3": RoadEdgeAttributes("fixture-top-3", "primary", 100.0, 13.88, False, False, 6.0),
            "fixture-bottom-1": RoadEdgeAttributes("fixture-bottom-1", "secondary", 200.0, 11.11, False, False, 14.0),
            "fixture-bottom-2": RoadEdgeAttributes("fixture-bottom-2", "secondary", 200.0, 11.11, False, False, 15.0),
            "fixture-bottom-3": RoadEdgeAttributes("fixture-bottom-3", "secondary", 200.0, 11.11, False, False, 12.0),
        }

        weather_by_edge: dict[str, list[WeatherRecord]] = {edge_id: [] for edge_id in roads}
        sensors_by_edge: dict[str, list[SensorRecord]] = {edge_id: [] for edge_id in roads}
        ground_truth_by_edge: dict[str, list[GroundTruthEvent]] = {edge_id: [] for edge_id in roads}
        past_flood_events: dict[str, list[datetime]] = {edge_id: [] for edge_id in roads}

        all_timestamps: list[datetime] = []
        source_ids = []

        clock_cursor = self.base_time

        for idx, scenario_name in enumerate(self.scenarios):
            source_ids.append(f"sim:{scenario_name}:seed_{self.seed + idx}")
            scenario = seeded_scenario(scenario_name, seed=self.seed + idx)
            clock = SimulationClock(clock_cursor)
            res = generate_events(scenario, seed=self.seed + idx, clock=clock)

            for event in res.events:
                ts = event.occurred_at
                all_timestamps.append(ts)
                payload = event.payload
                targets = payload.get("target_edge_ids") or list(roads.keys())

                if event.event_type == EventType.RAINFALL_OBSERVATION:
                    rain = payload.get("rainfall_mm_per_hour")
                    # Weather applies to all edges in the simulated region
                    for edge_id in roads:
                        weather_by_edge[edge_id].append(
                            WeatherRecord(ts, rain, temperature_c=28.0, humidity_percent=80.0, wind_speed_mps=3.5)
                        )

                elif event.event_type == EventType.WATER_DEPTH_READING:
                    depth = payload.get("water_depth_cm")
                    quality = payload.get("quality", "SIMULATED")
                    sid = payload.get("sensor_id", "sim-water")
                    rain = payload.get("rainfall_mm_per_hour")
                    for edge_id in targets:
                        if edge_id in sensors_by_edge:
                            sensors_by_edge[edge_id].append(SensorRecord(ts, depth, quality, sid))
                            ground_truth_by_edge[edge_id].append(GroundTruthEvent(ts, water_depth_cm=depth, event_type="sensor"))
                        if rain is not None and edge_id in weather_by_edge:
                            weather_by_edge[edge_id].append(WeatherRecord(ts, rain))

                elif event.event_type in (EventType.FLOOD_ZONE_ACTIVATED, EventType.FLOOD_ZONE_UPDATED):
                    sev = payload.get("severity", "HIGH")
                    for edge_id in targets:
                        if edge_id in ground_truth_by_edge:
                            ground_truth_by_edge[edge_id].append(GroundTruthEvent(ts, severity=sev, event_type="flood_zone"))

                elif event.event_type == EventType.INCIDENT_REPORTED:
                    sev = payload.get("severity", "HIGH")
                    for edge_id in targets:
                        if edge_id in ground_truth_by_edge:
                            ground_truth_by_edge[edge_id].append(GroundTruthEvent(ts, severity=sev, event_type="incident"))

            # Advance clock for next scenario (e.g. 1 hour gap)
            clock_cursor = clock_cursor + scenario.duration + scenario.duration

        min_t = min(all_timestamps) if all_timestamps else self.base_time
        max_t = max(all_timestamps) if all_timestamps else self.base_time

        return SourceBundle(
            source_type="SYNTHETIC",
            source_identifiers=source_ids,
            roads=roads,
            weather_by_edge=weather_by_edge,
            sensors_by_edge=sensors_by_edge,
            ground_truth_by_edge=ground_truth_by_edge,
            past_flood_events=past_flood_events,
            min_time=min_t,
            max_time=max_t,
        )


class DatabaseSource(DataSourceAdapter):
    """Reads real environmental and road observations from PostgreSQL/PostGIS.

    Provenance is strictly marked as REAL.
    """

    def __init__(self, db_url: str | None = None) -> None:
        self.db_url = db_url

    def is_available(self) -> bool:
        return False  # Real PostGIS local environment requires running DB

    def load_data(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> SourceBundle:
        raise RuntimeError("DatabaseSource BLOCKED: PostgreSQL/PostGIS instance is not currently available locally.")

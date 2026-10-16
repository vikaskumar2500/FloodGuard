from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from app.core.config import Settings
from app.risk.config import RiskConfig
from app.risk.costs import build_edge_costs
from app.risk.models import (
    EdgeEvidence,
    FloodZoneEvidence,
    IncidentEvidence,
    RiskSnapshot,
    SensorEvidence,
)
from app.risk.service import evaluate_graph, summarize_route
from app.routing import astar
from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode, assemble_geometry

from .coordinator import (
    RealtimeRerouteCoordinator,
    ReplacementRoute,
    RouteEvaluation,
    RuntimeRiskState,
)
from .event_bus import InMemoryEventBus
from .publisher import RealtimePublisher
from .registry import ActiveRoute, ActiveRouteRegistry
from .rerouting import RouteReroutingService
from .simulation_models import SimulationEvent, SimulationEventType

logger = logging.getLogger("floodguard.realtime")

NS = UUID("86f3949b-9ba7-4e3b-aef1-65d940a08754")


def _id(name: str) -> UUID:
    return uuid5(NS, name)


class FixtureEnvironment:
    def __init__(
        self,
        settings: Settings | None = None,
        prediction_service: Any = None,
        fusion_service: Any = None,
    ) -> None:
        self.settings = settings
        self.prediction_service = prediction_service
        self.fusion_service = fusion_service
        self.graph = RoutingGraph()
        coordinates = {
            "A": (0.0, 0.0),
            "B": (0.001, 0.0),
            "C": (0.002, 0.0),
            "D": (0.003, 0.0),
            "E": (0.0, 0.001),
            "F": (0.0015, 0.001),
        }
        self.nodes = {name: _id(f"node-{name}") for name in coordinates}
        for name, coordinate in coordinates.items():
            self.graph.add_node(RoutingNode(self.nodes[name], coordinate))
        specs = [
            ("top-1", "A", "B", 100, 60),
            ("top-2", "B", "C", 100, 60),
            ("top-3", "C", "D", 100, 60),
            ("bottom-1", "A", "E", 200, 70),
            ("bottom-2", "E", "F", 200, 70),
            ("bottom-3", "F", "D", 200, 70),
        ]
        self.aliases: dict[str, UUID] = {}
        for name, source, target, distance, seconds in specs:
            edge_id = _id(f"edge-{name}")
            self.aliases[f"fixture-{name}"] = edge_id
            self.graph.add_edge(
                RoutingEdge(
                    edge_id,
                    self.nodes[source],
                    self.nodes[target],
                    distance,
                    seconds,
                    (coordinates[source], coordinates[target]),
                )
            )
        self.graph.validate()
        self.evidence: dict[UUID, EdgeEvidence] = {
            edge_id: EdgeEvidence() for edge_id in self.graph.edges
        }
        self.snapshot = evaluate_graph(self.graph, {}, datetime.now(UTC), RiskConfig())

    def apply(self, event: SimulationEvent) -> dict[str, tuple[float, str, bool]]:
        targets = event.payload.get("target_edge_ids", ())
        edge_ids = [self.aliases[name] for name in targets if name in self.aliases]
        payload = event.payload
        if event.event_type == SimulationEventType.WATER_DEPTH_READING:
            for edge_id in edge_ids:
                self.evidence[edge_id].sensors = [
                    SensorEvidence(
                        payload.get("water_depth_cm"),
                        payload.get("rainfall_mm_per_hour"),
                        event.occurred_at,
                        payload.get("quality", "SIMULATED"),
                    )
                ]
        elif event.event_type in {
            SimulationEventType.FLOOD_ZONE_ACTIVATED,
            SimulationEventType.FLOOD_ZONE_UPDATED,
        }:
            zone = FloodZoneEvidence(
                float(payload["risk_score"]),
                float(payload.get("confidence", 0.5)),
                str(payload["severity"]),
                datetime.now(UTC) - event.occurred_at,
            )
            for edge_id in edge_ids:
                self.evidence[edge_id].flood_zones = [zone]
        elif event.event_type == SimulationEventType.FLOOD_ZONE_CLEARED:
            for edge_id in edge_ids:
                self.evidence[edge_id].flood_zones.clear()
        elif event.event_type == SimulationEventType.INCIDENT_REPORTED:
            incident = IncidentEvidence(
                str(payload["severity"]), "REPORTED", payload.get("confidence"), event.occurred_at
            )
            for edge_id in edge_ids:
                self.evidence[edge_id].incidents = [incident]
        elif event.event_type == SimulationEventType.INCIDENT_RESOLVED:
            for edge_id in edge_ids:
                self.evidence[edge_id].incidents.clear()
        elif (
            event.event_type == SimulationEventType.SENSOR_HEALTH_CHANGED
            and payload.get("status") == "OFFLINE"
        ):
            for edge_id in edge_ids:
                self.evidence[edge_id].sensors.clear()
        self.snapshot = evaluate_graph(self.graph, self.evidence, event.occurred_at, RiskConfig())
        return {
            str(self.aliases[name]): (
                self.snapshot.assessments[self.aliases[name]].risk_score,
                self.snapshot.assessments[self.aliases[name]].risk_level,
                self.snapshot.assessments[self.aliases[name]].risk_level == "SEVERE",
            )
            for name in targets
            if name in self.aliases
        }

    def _get_fused_assessments(self) -> dict[UUID, Any]:
        assessments = self.snapshot.assessments
        if (
            self.fusion_service is not None
            and self.prediction_service is not None
            and self.prediction_service.is_available
            and getattr(self.prediction_service, "model", None) is not None
        ):
            now = self.snapshot.evaluated_at
            try:
                records = [
                    self.prediction_service.feature_builder.build_features(
                        self.graph.edges[eid], now, evidence=self.evidence.get(eid)
                    )
                    for eid in self.graph.edges
                ]
                probs = self.prediction_service.model.predict_proba(records)
                from app.ml.models import MLFloodPrediction

                preds = {
                    eid: MLFloodPrediction(
                        edge_id=eid,
                        probability=float(probs[idx][1]),
                        predicted_class=(
                            1 if probs[idx][1] >= self.prediction_service.threshold else 0
                        ),
                        threshold=self.prediction_service.threshold,
                        model_name="XGBoost Classifier",
                        model_version=self.prediction_service.model_version,
                        feature_version="v1",
                        dataset_version="v1",
                        inference_time_ms=0.0,
                        evaluated_at=now,
                    )
                    for idx, eid in enumerate(self.graph.edges)
                }
                mode = self.settings.ml_mode if self.settings else "SHADOW"
                return self.fusion_service.fuse_assessments(assessments, preds, mode=mode)
            except Exception as err:
                logger.warning("Fixture ML fusion error: %s", err)
        return assessments

    def _route(self, mode: str):
        costs = build_edge_costs(self.graph, self._get_fused_assessments(), mode, RiskConfig())
        return astar.find_path(self.graph, self.nodes["A"], self.nodes["D"], costs=costs)

    def evaluation(self, route: ActiveRoute) -> RouteEvaluation:
        edge_ids = tuple(UUID(value) for value in route.edge_ids)
        path = self._path(edge_ids)
        fused = self._get_fused_assessments()
        fused_snapshot = RiskSnapshot(self.snapshot.evaluated_at, self.snapshot.version, fused)
        summary = summarize_route(self.graph, path, fused_snapshot, RiskConfig())
        return RouteEvaluation(
            summary.risk_score,
            summary.risk_level,
            summary.confidence,
            self._segments(edge_ids, fused),
        )

    def replacement(self, route: ActiveRoute) -> ReplacementRoute | None:
        path = self._route(route.mode)
        if tuple(str(value) for value in path.edge_ids) == tuple(route.edge_ids):
            return None
        fused = self._get_fused_assessments()
        fused_snapshot = RiskSnapshot(self.snapshot.evaluated_at, self.snapshot.version, fused)
        summary = summarize_route(self.graph, path, fused_snapshot, RiskConfig())
        geometry = assemble_geometry(self.graph, path.edge_ids)
        return ReplacementRoute(
            str(uuid4()),
            [str(value) for value in path.edge_ids],
            summary.risk_score,
            summary.risk_level,
            summary.confidence,
            sum(self.graph.edges[value].base_travel_time_s for value in path.edge_ids),
            sum(self.graph.edges[value].distance_m for value in path.edge_ids),
            {"type": "LineString", "coordinates": list(geometry.coordinates)},
            self._segments(path.edge_ids, fused),
        )

    def initial(self, mode: str) -> ReplacementRoute:
        path = self._route(mode)
        fused = self._get_fused_assessments()
        fused_snapshot = RiskSnapshot(self.snapshot.evaluated_at, self.snapshot.version, fused)
        summary = summarize_route(self.graph, path, fused_snapshot, RiskConfig())
        geometry = assemble_geometry(self.graph, path.edge_ids)
        return ReplacementRoute(
            str(uuid4()),
            [str(value) for value in path.edge_ids],
            summary.risk_score,
            summary.risk_level,
            summary.confidence,
            sum(self.graph.edges[value].base_travel_time_s for value in path.edge_ids),
            sum(self.graph.edges[value].distance_m for value in path.edge_ids),
            {"type": "LineString", "coordinates": list(geometry.coordinates)},
            self._segments(path.edge_ids, fused),
        )

    def _path(self, edge_ids: tuple[UUID, ...]):
        from app.routing.models import PathResult

        nodes = (self.graph.edges[edge_ids[0]].source,) + tuple(
            self.graph.edges[e].target for e in edge_ids
        )
        return PathResult(True, edge_ids, nodes, 0, 0)

    def _segments(
        self,
        edge_ids: tuple[UUID, ...] | list[UUID],
        assessments: dict[UUID, Any] | None = None,
    ) -> list[dict]:
        result = []
        source_assessments = (
            assessments if assessments is not None else self._get_fused_assessments()
        )
        for edge_id in edge_ids:
            assessment = source_assessments.get(edge_id, self.snapshot.assessments[edge_id])
            seg_dict = {
                "edgeId": str(edge_id),
                "riskScore": assessment.risk_score,
                "riskLevel": assessment.risk_level,
                "confidence": assessment.confidence,
                "explanation": assessment.explanation,
                "geometry": {
                    "type": "LineString",
                    "coordinates": list(self.graph.edges[edge_id].geometry),
                },
            }
            if hasattr(assessment, "ml_probability"):
                seg_dict["mlProbability"] = assessment.ml_probability
                seg_dict["deterministicRisk"] = assessment.deterministic_risk_score
                seg_dict["fusedRisk"] = assessment.fused_risk_score
            result.append(seg_dict)
        return result


@dataclass
class FloodGuardRuntime:
    event_bus: InMemoryEventBus
    route_registry: ActiveRouteRegistry
    realtime_publisher: RealtimePublisher
    runtime_risk_state: RuntimeRiskState
    reroute_coordinator: RealtimeRerouteCoordinator
    fixture: FixtureEnvironment

    @classmethod
    def create(
        cls,
        settings: Settings,
        prediction_service: Any = None,
        fusion_service: Any = None,
    ) -> FloodGuardRuntime:
        bus = InMemoryEventBus()
        registry = ActiveRouteRegistry(ttl_seconds=settings.active_route_ttl_seconds)
        publisher = RealtimePublisher(settings.realtime_queue_size)
        risk_state = RuntimeRiskState(settings.risk_change_threshold)
        fixture = FixtureEnvironment(
            settings=settings,
            prediction_service=prediction_service,
            fusion_service=fusion_service,
        )

        runtime: FloodGuardRuntime | None = None

        async def evaluate(route: ActiveRoute, revision: int) -> RouteEvaluation:
            assert runtime is not None
            first_eid = None
            if route.edge_ids:
                try:
                    first_eid = UUID(route.edge_ids[0])
                except (ValueError, TypeError):
                    pass
            if first_eid and first_eid in runtime.fixture.graph.edges:
                return runtime.fixture.evaluation(route)

            # Evaluate non-fixture active route using runtime_risk_state
            max_score = route.risk_score
            highest_level = route.risk_level
            level_rank = {"LOW": 1, "MODERATE": 2, "HIGH": 3, "SEVERE": 4}

            segments = []
            for eid_str in route.edge_ids:
                if eid_str in runtime.runtime_risk_state._scores:
                    score, level, _ = runtime.runtime_risk_state._scores[eid_str]
                else:
                    score, level = route.risk_score, route.risk_level

                if score > max_score:
                    max_score = score
                if level_rank.get(level, 1) > level_rank.get(highest_level, 1):
                    highest_level = level

                segments.append(
                    {
                        "edgeId": eid_str,
                        "riskScore": score,
                        "riskLevel": level,
                        "confidence": 1.0,
                        "explanation": f"Observed flood risk: {level}",
                        "geometry": {"type": "LineString", "coordinates": []},
                    }
                )

            return RouteEvaluation(
                risk_score=max_score,
                risk_level=highest_level,
                confidence=max(route.risk_confidence, 0.95),
                risk_segments=segments,
            )

        async def calculate(route: ActiveRoute, revision: int) -> ReplacementRoute | None:
            assert runtime is not None
            first_eid = None
            if route.edge_ids:
                try:
                    first_eid = UUID(route.edge_ids[0])
                except (ValueError, TypeError):
                    pass
            if first_eid and first_eid in runtime.fixture.graph.edges:
                await asyncio.sleep(1.2)
                return runtime.fixture.replacement(route)

            return None

        coordinator = RealtimeRerouteCoordinator(
            registry,
            publisher,
            RouteReroutingService(
                reroute_improvement_threshold=settings.reroute_min_risk_improvement,
                unsafe_threshold=settings.reroute_unsafe_threshold,
                recovery_threshold=settings.reroute_recovery_threshold,
                cooldown_seconds=settings.reroute_cooldown_seconds,
            ),
            evaluate,
            calculate,
        )
        runtime = cls(bus, registry, publisher, risk_state, coordinator, fixture)
        bus.subscribe("risk.edges_changed", runtime._risk_changed)
        return runtime

    async def _risk_changed(self, event: dict) -> None:
        await self.reroute_coordinator.risk_edges_changed(
            event["riskRevision"], set(event["edgeIds"])
        )

    async def apply_simulation(self, event: SimulationEvent) -> dict:
        if str(event.event_id) in self.runtime_risk_state._event_ids:
            return {
                "accepted": True,
                "duplicate": True,
                "materialChange": False,
                "riskRevision": self.runtime_risk_state.revision,
                "affectedEdgeIds": [],
            }
        revision, edges = self.runtime_risk_state.apply(
            str(event.event_id), self.fixture.apply(event)
        )
        logger.info(
            "simulation_event_applied",
            extra={
                "simulation_event_id": str(event.event_id),
                "scenario_id": event.scenario_id,
                "event_type": event.event_type.value,
                "risk_revision": revision,
                "material_change": bool(edges),
                "affected_edge_ids": sorted(edges),
            },
        )
        if edges:
            logger.info(
                "risk_revision_advanced",
                extra={
                    "risk_revision": revision,
                    "source_event_id": str(event.event_id),
                    "affected_edge_ids": sorted(edges),
                },
            )
            await self.event_bus.publish_async(
                {
                    "eventType": "risk.edges_changed",
                    "riskRevision": revision,
                    "edgeIds": sorted(edges),
                    "sourceEventId": str(event.event_id),
                }
            )
        return {
            "accepted": True,
            "duplicate": False,
            "materialChange": bool(edges),
            "riskRevision": revision,
            "affectedEdgeIds": sorted(edges),
        }

    def close(self) -> None:
        self.realtime_publisher.close_all()
        self.route_registry.clear()
        self.event_bus.reset()

    def reset(self) -> None:
        self.realtime_publisher.close_all()
        self.route_registry.clear()
        self.fixture = FixtureEnvironment()
        self.runtime_risk_state = RuntimeRiskState()
        self.reroute_coordinator.reroute_count = 0

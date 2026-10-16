import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .events import (
    RouteInvalidatedData,
    RouteRecalculatedData,
    RouteRerouteFailedData,
    RouteReroutingData,
    RouteRiskUpdatedData,
)
from .publisher import RealtimePublisher
from .registry import ActiveRoute, ActiveRouteRegistry
from .rerouting import RouteImpactDetector, RouteReroutingService

logger = logging.getLogger("floodguard.realtime")


@dataclass(frozen=True)
class RouteEvaluation:
    risk_score: float
    risk_level: str
    confidence: float
    risk_segments: list[dict[str, Any]]


@dataclass(frozen=True)
class ReplacementRoute:
    route_id: str
    edge_ids: list[str]
    risk_score: float
    risk_level: str
    confidence: float
    eta_seconds: float
    distance_meters: float
    geometry: dict[str, Any]
    risk_segments: list[dict[str, Any]]
    algorithm: str = "ASTAR"


class RuntimeRiskState:
    def __init__(self, threshold: float = 0.3) -> None:
        self.threshold = threshold
        self.revision = 0
        self._scores: dict[str, tuple[float, str, bool]] = {}
        self._event_ids: set[str] = set()

    def apply(
        self, event_id: str, changes: dict[str, tuple[float, str, bool]]
    ) -> tuple[int, set[str]]:
        if event_id in self._event_ids:
            return self.revision, set()
        self._event_ids.add(event_id)
        material: set[str] = set()
        for edge_id, value in changes.items():
            old = self._scores.get(edge_id)
            self._scores[edge_id] = value
            if (
                old is None
                or old[1] != value[1]
                or old[2] != value[2]
                or abs(old[0] - value[0]) >= self.threshold
            ):
                material.add(edge_id)
        if material:
            self.revision += 1
        return self.revision, material


class RealtimeRerouteCoordinator:
    """Consumes material risk changes and serializes rerouting per active route."""

    def __init__(
        self,
        registry: ActiveRouteRegistry,
        publisher: RealtimePublisher,
        policy: RouteReroutingService,
        evaluate: Callable[[ActiveRoute, int], Awaitable[RouteEvaluation]],
        calculate: Callable[[ActiveRoute, int], Awaitable[ReplacementRoute | None]],
    ) -> None:
        self.registry, self.publisher, self.policy = registry, publisher, policy
        self.evaluate, self.calculate = evaluate, calculate
        self.detector = RouteImpactDetector(registry)
        self._locks: dict[str, asyncio.Lock] = {}
        self._pending: dict[str, tuple[int, set[str]]] = {}
        self.reroute_count = 0

    async def risk_edges_changed(self, revision: int, edge_ids: set[str]) -> None:
        await asyncio.gather(
            *(
                self._process(route_id, revision, edge_ids)
                for route_id in self.detector.detect_affected_routes(edge_ids)
            )
        )

    async def _process(self, route_id: str, revision: int, edge_ids: set[str]) -> None:
        logger.info(
            "route_impacted",
            extra={
                "route_id": route_id,
                "risk_revision": revision,
                "affected_edge_ids": sorted(edge_ids),
            },
        )
        lock = self._locks.setdefault(route_id, asyncio.Lock())
        if lock.locked():
            old_revision, old_edges = self._pending.get(route_id, (0, set()))
            self._pending[route_id] = (max(old_revision, revision), old_edges | edge_ids)
            return
        async with lock:
            await self._evaluate_once(route_id, revision, edge_ids)
            pending = self._pending.pop(route_id, None)
            if pending and self.registry.get(route_id):
                await self._evaluate_once(route_id, *pending)

    async def _evaluate_once(self, route_id: str, revision: int, edge_ids: set[str]) -> None:
        route = self.registry.get(route_id)
        if route is None or revision <= route.evaluated_risk_revision:
            return
        current = await self.evaluate(route, revision)
        route = self.registry.update(
            route_id,
            risk_score=current.risk_score,
            risk_level=current.risk_level,
            risk_confidence=current.confidence,
            evaluated_risk_revision=revision,
        )
        payload = RouteRiskUpdatedData(
            riskScore=current.risk_score,
            riskLevel=current.risk_level,
            riskConfidence=current.confidence,
            riskSegments=current.risk_segments,
        )
        if current.risk_level not in {"HIGH", "SEVERE"}:
            self.publisher.publish(route_id, "route.risk_updated", payload, risk_revision=revision)
            return
        invalid = RouteInvalidatedData(**payload.model_dump(), affectedEdgeIds=sorted(edge_ids))
        self.publisher.publish(route_id, "route.invalidated", invalid, risk_revision=revision)
        logger.info(
            "route_invalidated",
            extra={
                "route_id": route_id,
                "risk_revision": revision,
                "risk_score": current.risk_score,
                "affected_edge_ids": sorted(edge_ids),
            },
        )
        self.publisher.publish(
            route_id,
            "route.rerouting",
            RouteReroutingData(reason="FLOOD_RISK"),
            risk_revision=revision,
        )
        logger.info(
            "reroute_started",
            extra={
                "route_id": route_id,
                "risk_revision": revision,
                "mode": route.mode,
            },
        )
        self.reroute_count += 1
        candidate = await self.calculate(route, revision)
        if self.registry.get(route_id) is None:
            logger.info("route_expired", extra={"route_id": route_id})
            return
        if candidate is None:
            self.publisher.publish(
                route_id,
                "route.reroute_failed",
                RouteRerouteFailedData(
                    routeId=route_id,
                    reason="NO_ALTERNATIVE",
                    currentRisk=current.risk_score,
                    currentRiskLevel=current.risk_level,
                    riskConfidence=current.confidence,
                    riskRevision=revision,
                    remainsTraversable=True,
                ),
                risk_revision=revision,
            )
            logger.info(
                "reroute_failed",
                extra={
                    "route_id": route_id,
                    "risk_revision": revision,
                    "reason": "NO_ALTERNATIVE",
                },
            )
            return
        decision = self.policy.decide(
            mode=route.mode,
            current_risk=current.risk_score,
            current_eta_s=route.current_eta_s,
            candidate_risk=candidate.risk_score,
            candidate_eta_s=candidate.eta_seconds,
            affected_edge_ids=edge_ids,
            route_is_affected=True,
            current_level=current.risk_level,
            candidate_level=candidate.risk_level,
            unsafe_latched=route.unsafe_latched,
            last_rerouted_at=route.last_rerouted_at,
        )
        self.registry.update(route_id, unsafe_latched=decision.unsafe_latched)
        if not decision.should_reroute:
            self.publisher.publish(route_id, "route.risk_updated", payload, risk_revision=revision)
            return
        new_route = ActiveRoute(
            route_id=candidate.route_id,
            graph_version_id=route.graph_version_id,
            mode=route.mode,
            source=route.source,
            destination=route.destination,
            edge_ids=candidate.edge_ids,
            risk_score=candidate.risk_score,
            risk_level=candidate.risk_level,
            risk_confidence=candidate.confidence,
            current_eta_s=candidate.eta_seconds,
            evaluated_risk_revision=revision,
            last_rerouted_at=datetime.now(UTC),
            metadata=route.metadata,
        )
        self.registry.replace(route_id, new_route)
        data = RouteRecalculatedData(
            oldRouteId=route_id,
            newRouteId=candidate.route_id,
            reason=decision.reason,
            mode=route.mode,
            algorithm=candidate.algorithm,
            oldRiskScore=current.risk_score,
            newRiskScore=candidate.risk_score,
            oldRiskLevel=current.risk_level,
            newRiskLevel=candidate.risk_level,
            oldRiskConfidence=current.confidence,
            newRiskConfidence=candidate.confidence,
            oldEtaSeconds=route.current_eta_s,
            newEtaSeconds=candidate.eta_seconds,
            etaDeltaSeconds=candidate.eta_seconds - route.current_eta_s,
            riskReduction=current.risk_score - candidate.risk_score,
            distanceMeters=candidate.distance_meters,
            geometry=candidate.geometry,
            riskSegments=candidate.risk_segments,
            graphVersionId=route.graph_version_id,
            riskRevision=revision,
        )
        self.publisher.publish(route_id, "route.recalculated", data, risk_revision=revision)
        logger.info(
            "reroute_completed",
            extra={
                "route_id": route_id,
                "new_route_id": candidate.route_id,
                "risk_revision": revision,
                "eta_delta_seconds": data.etaDeltaSeconds,
                "risk_reduction": data.riskReduction,
            },
        )

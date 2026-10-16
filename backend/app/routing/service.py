from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID, uuid4

from geoalchemy2 import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.keys import compute_config_hash
from app.cache.serializer import route_calculation_to_dto
from app.core.config import Settings
from app.models import Route, RouteSegment
from app.risk.config import RiskConfig
from app.risk.costs import build_edge_costs
from app.risk.models import RiskSnapshot
from app.risk.repository import RiskEvidenceRepository
from app.risk.service import RouteRiskSummary, evaluate_graph, summarize_route

from . import astar, dijkstra
from .exceptions import GraphUnavailable, NoRouteFound, SnapDistanceExceeded
from .models import PathResult, RoutingGraph, assemble_geometry
from .repository import RoutingGraphRepository, validate_coordinate

if TYPE_CHECKING:
    from app.cache.graph_cache import GraphCache
    from app.cache.risk_cache import RiskSnapshotCache
    from app.cache.route_cache import RouteCache
    from app.ml.service import FloodPredictionService
    from app.risk.fusion import RiskFusionService
    from app.risk.models import EdgeEvidence

from app.schemas.routes import MLRouteMetadata

RouteMode = Literal["FASTEST", "BALANCED", "SAFEST"]
Algorithm = Literal["DIJKSTRA", "ASTAR"]


@dataclass(frozen=True)
class RouteRiskSegment:
    edge_id: UUID
    risk_score: float
    risk_level: str
    confidence: float
    explanation: str
    geometry_coordinates: tuple[tuple[float, float], ...]
    ml_probability: float | None = None
    deterministic_risk: float | None = None
    fused_risk: float | None = None


@dataclass(frozen=True)
class RouteCalculation:
    route_id: UUID
    graph_version_id: UUID
    algorithm: Algorithm
    mode: RouteMode
    distance_m: float
    estimated_time_s: float
    risk_score: float
    risk_level: str
    risk_confidence: float
    max_edge_risk: float
    high_risk_distance_m: float
    risk_segments: tuple[RouteRiskSegment, ...]
    risk_model_active: bool
    expanded_nodes: int
    geometry_type: str
    geometry_coordinates: tuple[tuple[float, float], ...]
    is_cache_hit: bool = False
    ml: MLRouteMetadata | None = None


def line_wkt(coordinates: tuple[tuple[float, float], ...]) -> WKTElement:
    values = ",".join(f"{longitude} {latitude}" for longitude, latitude in coordinates)
    return WKTElement(f"LINESTRING({values})", srid=4326)


def persist_route(
    session: AsyncSession,
    *,
    graph_version_id: UUID,
    source: tuple[float, float],
    destination: tuple[float, float],
    mode: RouteMode,
    algorithm: Algorithm,
    graph: RoutingGraph,
    path: PathResult,
    snapshot: RiskSnapshot,
    risk_summary: RouteRiskSummary,
) -> Route:
    geometry = assemble_geometry(graph, path.edge_ids)
    if not geometry.coordinates:
        coordinate = graph.nodes[path.node_ids[0]].coordinate
        geometry = type(geometry)("LineString", (coordinate, coordinate))
    route_id = uuid4()
    route = Route(
        id=route_id,
        graph_version_id=graph_version_id,
        source_location=WKTElement(f"POINT({source[0]} {source[1]})", srid=4326),
        destination_location=WKTElement(f"POINT({destination[0]} {destination[1]})", srid=4326),
        mode=mode,
        algorithm=algorithm,
        total_distance_m=sum(graph.edges[edge_id].distance_m for edge_id in path.edge_ids),
        estimated_time_s=sum(graph.edges[edge_id].base_travel_time_s for edge_id in path.edge_ids),
        risk_score=risk_summary.risk_score,
        geometry=line_wkt(geometry.coordinates),
        risk_version=snapshot.version,
        policy_version=f"{mode.lower()}-v1",
        attributes={
            "risk_model_active": True,
            "expanded_nodes": path.expanded_nodes,
            "max_edge_risk": risk_summary.max_edge_risk,
            "high_risk_distance_m": risk_summary.high_risk_distance_m,
        },
    )
    session.add(route)
    for sequence, edge_id in enumerate(path.edge_ids):
        edge = graph.edges[edge_id]
        session.add(
            RouteSegment(
                route_id=route_id,
                road_edge_id=edge.id,
                graph_version_id=graph_version_id,
                sequence=sequence,
                distance_m=edge.distance_m,
                travel_time_s=edge.base_travel_time_s,
                risk_score=snapshot.for_edge(edge.id).risk_score,
                attributes={
                    "risk_model_active": True,
                    "risk_level": snapshot.for_edge(edge.id).risk_level,
                    "confidence": snapshot.for_edge(edge.id).confidence,
                    "explanation": snapshot.for_edge(edge.id).explanation,
                },
            )
        )
    return route


async def calculate_route(
    session: AsyncSession,
    *,
    source: tuple[float, float],
    destination: tuple[float, float],
    mode: RouteMode,
    algorithm: Algorithm,
    settings: Settings,
    graph_cache: GraphCache | None = None,
    risk_cache: RiskSnapshotCache | None = None,
    route_cache: RouteCache | None = None,
    risk_revision: int = 0,
    prediction_service: FloodPredictionService | None = None,
    fusion_service: RiskFusionService | None = None,
) -> RouteCalculation:
    validate_coordinate(*source)
    validate_coordinate(*destination)
    repository = RoutingGraphRepository(session)
    version = await repository.find_graph_version(*source, *destination)
    if version is None:
        raise GraphUnavailable("no graph version covers both route coordinates")

    source_node = await repository.nearest_node(
        version.id, source[0], source[1], settings.max_route_snap_distance_m
    )
    destination_node = await repository.nearest_node(
        version.id, destination[0], destination[1], settings.max_route_snap_distance_m
    )
    if source_node is None or destination_node is None:
        raise SnapDistanceExceeded("a route endpoint is too far from a routable road node")

    config_hash = compute_config_hash(
        settings.risk_balanced_penalty_seconds,
        settings.risk_safest_penalty_seconds,
        settings.risk_safest_unknown_penalty_seconds,
        settings.max_routing_expansions,
        settings.ml_mode,
        settings.ml_risk_weight,
    )

    if route_cache is not None:
        cached_template = await route_cache.get(
            version.id,
            source_node[0],
            destination_node[0],
            mode,
            algorithm,
            risk_revision,
            config_hash,
        )
        if cached_template is not None:
            new_route_id = uuid4()
            cached_ml_metadata = None
            if cached_template.ml_available or cached_template.ml_mode != "DISABLED":
                cached_ml_metadata = MLRouteMetadata(
                    mode=cached_template.ml_mode,  # type: ignore[arg-type]
                    available=cached_template.ml_available,
                    modelVersion=cached_template.ml_model_version or settings.ml_model_version,
                    predictionHorizonMinutes=30,
                )
            return RouteCalculation(
                route_id=new_route_id,
                graph_version_id=UUID(cached_template.graph_version_id),
                algorithm=cached_template.algorithm,
                mode=cached_template.mode,
                distance_m=cached_template.distance_m,
                estimated_time_s=cached_template.estimated_time_s,
                risk_score=cached_template.risk_score,
                risk_level=cached_template.risk_level,
                risk_confidence=cached_template.risk_confidence,
                max_edge_risk=cached_template.max_edge_risk,
                high_risk_distance_m=cached_template.high_risk_distance_m,
                risk_segments=tuple(
                    RouteRiskSegment(
                        edge_id=UUID(s.edge_id),
                        risk_score=s.risk_score,
                        risk_level=s.risk_level,
                        confidence=s.confidence,
                        explanation=s.explanation,
                        geometry_coordinates=s.geometry_coordinates,
                        ml_probability=s.ml_probability,
                        deterministic_risk=s.deterministic_risk,
                        fused_risk=s.fused_risk,
                    )
                    for s in cached_template.risk_segments
                ),
                risk_model_active=cached_template.risk_model_active,
                expanded_nodes=cached_template.expanded_nodes,
                geometry_type=cached_template.geometry_type,
                geometry_coordinates=cached_template.geometry_coordinates,
                is_cache_hit=True,
                ml=cached_ml_metadata,
            )

    graph = None
    if graph_cache is not None:
        graph = await graph_cache.get(version.id)
    if graph is None:
        try:
            graph = await repository.load_graph(version.id)
            if graph_cache is not None:
                await graph_cache.set(version.id, graph)
        except ValueError as error:
            raise GraphUnavailable("the selected graph version is empty or invalid") from error

    risk_config = RiskConfig(
        balanced_penalty_seconds=settings.risk_balanced_penalty_seconds,
        safest_penalty_seconds=settings.risk_safest_penalty_seconds,
        safest_unknown_penalty_seconds=settings.risk_safest_unknown_penalty_seconds,
    )

    snapshot = None
    if risk_cache is not None:
        snapshot = await risk_cache.get(version.id, risk_revision, config_hash)

    now = datetime.now(UTC)
    evidence: dict[UUID, EdgeEvidence] = {}
    if snapshot is None:
        evidence = await RiskEvidenceRepository(session).load_for_edges(
            tuple(graph.edges), now, risk_config
        )
        snapshot = evaluate_graph(graph, evidence, now, risk_config)
        if risk_cache is not None:
            await risk_cache.set(version.id, risk_revision, config_hash, snapshot)
    elif prediction_service is not None and prediction_service.is_available:
        evidence = await RiskEvidenceRepository(session).load_for_edges(
            tuple(graph.edges), now, risk_config
        )

    # ML Batch Prediction & Risk Fusion
    ml_predictions: dict[UUID, Any] = {}
    if prediction_service is not None and prediction_service.is_available:
        ml_predictions = await prediction_service.predict_edges(
            graph=graph,
            evidence_map=evidence,
            now=now,
            graph_version_id=version.id,
            risk_revision=risk_revision,
            config_hash=config_hash,
        )

    fused_assessments = snapshot.assessments
    if fusion_service is not None:
        fused_assessments = fusion_service.fuse_assessments(
            assessments=snapshot.assessments,
            predictions=ml_predictions,
            mode=settings.ml_mode,
        )

    costs = build_edge_costs(graph, fused_assessments, mode, risk_config)
    search = astar.find_path if algorithm == "ASTAR" else dijkstra.find_path
    path = search(
        graph,
        source_node[0],
        destination_node[0],
        max_expansions=settings.max_routing_expansions,
        costs=costs,
    )
    if not path.found:
        raise NoRouteFound("no directed route connects the selected locations")

    fused_snapshot = RiskSnapshot(snapshot.evaluated_at, snapshot.version, fused_assessments)
    risk_summary = summarize_route(graph, path, fused_snapshot, risk_config)
    route = persist_route(
        session,
        graph_version_id=version.id,
        source=source,
        destination=destination,
        mode=mode,
        algorithm=algorithm,
        graph=graph,
        path=path,
        snapshot=fused_snapshot,
        risk_summary=risk_summary,
    )
    await session.flush()
    geometry = assemble_geometry(graph, path.edge_ids)
    if not geometry.coordinates:
        coordinate = graph.nodes[path.node_ids[0]].coordinate
        geometry = type(geometry)("LineString", (coordinate, coordinate))
    risk_segments = tuple(
        RouteRiskSegment(
            edge_id=edge_id,
            risk_score=assessment.risk_score,
            risk_level=assessment.risk_level,
            confidence=assessment.confidence,
            explanation=assessment.explanation,
            geometry_coordinates=graph.edges[edge_id].geometry,
            ml_probability=(
                ml_predictions[edge_id].probability if edge_id in ml_predictions else None
            ),
            deterministic_risk=snapshot.assessments[edge_id].risk_score,
            fused_risk=fused_assessments[edge_id].risk_score,
        )
        for edge_id, assessment in zip(path.edge_ids, risk_summary.risk_segments, strict=True)
    )
    baseline_time = sum(graph.edges[edge_id].base_travel_time_s for edge_id in path.edge_ids)

    ml_metadata = None
    if (prediction_service and prediction_service.is_available) or settings.ml_mode != "DISABLED":
        ml_metadata = MLRouteMetadata(
            mode=settings.ml_mode,
            available=prediction_service.is_available if prediction_service else False,
            modelVersion=(
                prediction_service.model_version
                if prediction_service
                else settings.ml_model_version
            ),
            predictionHorizonMinutes=30,
        )

    calc = RouteCalculation(
        route_id=route.id,
        graph_version_id=version.id,
        algorithm=algorithm,
        mode=mode,
        distance_m=sum(graph.edges[edge_id].distance_m for edge_id in path.edge_ids),
        estimated_time_s=baseline_time,
        risk_score=risk_summary.risk_score,
        risk_level=risk_summary.risk_level,
        risk_confidence=risk_summary.confidence,
        max_edge_risk=risk_summary.max_edge_risk,
        high_risk_distance_m=risk_summary.high_risk_distance_m,
        risk_segments=risk_segments,
        risk_model_active=True,
        expanded_nodes=path.expanded_nodes,
        geometry_type=geometry.type,
        geometry_coordinates=geometry.coordinates,
        is_cache_hit=False,
        ml=ml_metadata,
    )
    if route_cache is not None:
        template = route_calculation_to_dto(
            calc,
            source_node[0],
            destination_node[0],
            risk_revision,
        )
        await route_cache.set(
            version.id,
            source_node[0],
            destination_node[0],
            mode,
            algorithm,
            risk_revision,
            config_hash,
            template,
        )
    return calc

import json
import logging
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.risk.models import EdgeRiskAssessment, RiskSnapshot
from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode

from .models import (
    CachedEdgeDTO,
    CachedGraphDTO,
    CachedNodeDTO,
    CachedRiskAssessmentDTO,
    CachedRiskSnapshotDTO,
    CachedRouteSegmentDTO,
    CachedRouteTemplateDTO,
)

logger = logging.getLogger("floodguard.cache")

T = TypeVar("T", bound=BaseModel)


def serialize_model(model: BaseModel) -> str:
    """Serialize Pydantic model to JSON string."""
    return model.model_dump_json()


def deserialize_model[T: BaseModel](raw_data: str | bytes, model_cls: type[T]) -> T | None:
    """Safely deserialize JSON string to Pydantic model.

    If data is corrupted or doesn't match the schema, returns None and logs a warning.
    """
    try:
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode("utf-8")
        return model_cls.model_validate_json(raw_data)
    except (json.JSONDecodeError, ValidationError, UnicodeDecodeError) as error:
        logger.warning(
            "cache_deserialization_corrupted",
            extra={"error_type": type(error).__name__, "model": model_cls.__name__},
        )
        return None


def graph_to_dto(graph_version_id: UUID | str, graph: RoutingGraph) -> CachedGraphDTO:
    nodes = [
        CachedNodeDTO(id=str(node.id), coordinate=node.coordinate) for node in graph.nodes.values()
    ]
    edges = [
        CachedEdgeDTO(
            id=str(edge.id),
            source=str(edge.source),
            target=str(edge.target),
            distance_m=edge.distance_m,
            base_travel_time_s=edge.base_travel_time_s,
            geometry=edge.geometry,
            speed_limit_mps=edge.speed_limit_mps,
        )
        for edge in graph.edges.values()
    ]
    return CachedGraphDTO(version_id=str(graph_version_id), nodes=nodes, edges=edges)


def dto_to_graph(dto: CachedGraphDTO) -> RoutingGraph:
    graph = RoutingGraph()
    for n in dto.nodes:
        graph.add_node(RoutingNode(UUID(n.id), n.coordinate))
    for e in dto.edges:
        graph.add_edge(
            RoutingEdge(
                UUID(e.id),
                UUID(e.source),
                UUID(e.target),
                e.distance_m,
                e.base_travel_time_s,
                e.geometry,
                e.speed_limit_mps,
            )
        )
    graph.validate()
    return graph


def risk_snapshot_to_dto(
    graph_version_id: UUID | str,
    risk_revision: int,
    snapshot: RiskSnapshot,
) -> CachedRiskSnapshotDTO:
    assessments = {
        str(edge_id): CachedRiskAssessmentDTO(
            edge_id=str(assessment.edge_id),
            risk_score=assessment.risk_score,
            risk_level=assessment.risk_level,
            confidence=assessment.confidence,
            flood_zone_score=assessment.flood_zone_score,
            water_depth_score=assessment.water_depth_score,
            rainfall_score=assessment.rainfall_score,
            prediction_score=assessment.prediction_score,
            incident_score=assessment.incident_score,
            evidence_age_seconds=assessment.evidence_age_seconds,
            explanation=assessment.explanation,
            high_risk_distance_m=assessment.high_risk_distance_m,
        )
        for edge_id, assessment in snapshot.assessments.items()
    }
    return CachedRiskSnapshotDTO(
        graph_version_id=str(graph_version_id),
        risk_revision=risk_revision,
        version=snapshot.version,
        evaluated_at_iso=snapshot.evaluated_at.isoformat(),
        assessments=assessments,
    )


def dto_to_risk_snapshot(dto: CachedRiskSnapshotDTO) -> RiskSnapshot:
    assessments = {
        UUID(edge_id_str): EdgeRiskAssessment(
            edge_id=UUID(item.edge_id),
            risk_score=item.risk_score,
            risk_level=item.risk_level,  # type: ignore
            confidence=item.confidence,
            flood_zone_score=item.flood_zone_score,
            water_depth_score=item.water_depth_score,
            rainfall_score=item.rainfall_score,
            prediction_score=item.prediction_score,
            incident_score=item.incident_score,
            evidence_age_seconds=item.evidence_age_seconds,
            explanation=item.explanation,
            high_risk_distance_m=item.high_risk_distance_m,
        )
        for edge_id_str, item in dto.assessments.items()
    }
    evaluated_at = datetime.fromisoformat(dto.evaluated_at_iso)
    if evaluated_at.tzinfo is None:
        evaluated_at = evaluated_at.replace(tzinfo=UTC)
    return RiskSnapshot(evaluated_at, dto.version, assessments)


def route_calculation_to_dto(
    result: "RouteCalculation",
    source_node_id: UUID | str,
    destination_node_id: UUID | str,
    risk_revision: int,
    node_ids: tuple[str, ...] = (),
) -> CachedRouteTemplateDTO:
    return CachedRouteTemplateDTO(
        graph_version_id=str(result.graph_version_id),
        algorithm=result.algorithm,
        mode=result.mode,
        source_node_id=str(source_node_id),
        destination_node_id=str(destination_node_id),
        distance_m=result.distance_m,
        estimated_time_s=result.estimated_time_s,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        risk_confidence=result.risk_confidence,
        max_edge_risk=result.max_edge_risk,
        high_risk_distance_m=result.high_risk_distance_m,
        expanded_nodes=result.expanded_nodes,
        risk_model_active=result.risk_model_active,
        edge_ids=tuple(str(s.edge_id) for s in result.risk_segments),
        node_ids=node_ids,
        risk_segments=tuple(
            CachedRouteSegmentDTO(
                edge_id=str(s.edge_id),
                risk_score=s.risk_score,
                risk_level=s.risk_level,
                confidence=s.confidence,
                explanation=s.explanation,
                geometry_coordinates=s.geometry_coordinates,
                ml_probability=s.ml_probability,
                deterministic_risk=s.deterministic_risk,
                fused_risk=s.fused_risk,
            )
            for s in result.risk_segments
        ),
        geometry_type=result.geometry_type,
        geometry_coordinates=result.geometry_coordinates,
        risk_revision=risk_revision,
        ml_mode=result.ml.mode if result.ml else "DISABLED",
        ml_available=result.ml.available if result.ml else False,
        ml_model_version=result.ml.model_version if result.ml else "",
    )

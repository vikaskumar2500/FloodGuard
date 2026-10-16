from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.routing.models import PathResult, RoutingGraph

from .config import RiskConfig
from .models import EdgeEvidence, EdgeRiskAssessment, RiskSnapshot
from .scoring import assess_edge


@dataclass(frozen=True)
class RouteRiskSummary:
    risk_score: float
    risk_level: str
    confidence: float
    max_edge_risk: float
    high_risk_distance_m: float
    risk_segments: tuple[EdgeRiskAssessment, ...]


def evaluate_graph(
    graph: RoutingGraph,
    evidence: dict[UUID, EdgeEvidence],
    now: datetime,
    config: RiskConfig,
) -> RiskSnapshot:
    assessments = {
        edge_id: assess_edge(
            edge_id,
            edge.distance_m,
            evidence.get(edge_id, EdgeEvidence()),
            now,
            config,
        )
        for edge_id, edge in graph.edges.items()
    }
    return RiskSnapshot(now, "deterministic-v1", assessments)


def summarize_route(
    graph: RoutingGraph,
    path: PathResult,
    snapshot: RiskSnapshot,
    config: RiskConfig,
) -> RouteRiskSummary:
    assessments = tuple(snapshot.for_edge(edge_id) for edge_id in path.edge_ids)
    total_distance = sum(graph.edges[edge_id].distance_m for edge_id in path.edge_ids)
    if not assessments or total_distance <= 0:
        return RouteRiskSummary(0.0, "LOW", 0.0, 0.0, 0.0, assessments)
    weighted_risk = (
        sum(
            graph.edges[edge_id].distance_m * assessment.risk_score
            for edge_id, assessment in zip(path.edge_ids, assessments, strict=True)
        )
        / total_distance
    )
    weighted_confidence = (
        sum(
            graph.edges[edge_id].distance_m * assessment.confidence
            for edge_id, assessment in zip(path.edge_ids, assessments, strict=True)
        )
        / total_distance
    )
    max_risk = max(assessment.risk_score for assessment in assessments)
    level = assessments[0].risk_level
    for assessment in assessments[1:]:
        if assessment.risk_score > weighted_risk:
            level = assessment.risk_level
    return RouteRiskSummary(
        risk_score=weighted_risk,
        risk_level=level,
        confidence=weighted_confidence,
        max_edge_risk=max_risk,
        high_risk_distance_m=sum(assessment.high_risk_distance_m for assessment in assessments),
        risk_segments=assessments,
    )

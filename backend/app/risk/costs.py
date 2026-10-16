from typing import Literal
from uuid import UUID

from app.routing.models import RoutingGraph

from .config import RiskConfig
from .models import EdgeRiskAssessment

RouteMode = Literal["FASTEST", "BALANCED", "SAFEST"]


def build_edge_costs(
    graph: RoutingGraph,
    assessments: dict[UUID, EdgeRiskAssessment],
    mode: RouteMode,
    config: RiskConfig,
) -> dict[UUID, float]:
    costs: dict[UUID, float] = {}
    for edge_id, edge in graph.edges.items():
        assessment = assessments[edge_id]
        if mode == "FASTEST":
            cost = edge.base_travel_time_s
        elif mode == "BALANCED":
            cost = edge.base_travel_time_s + (
                assessment.risk_score * config.balanced_penalty_seconds
            )
        else:
            cost = (
                edge.base_travel_time_s
                + (assessment.risk_score * config.safest_penalty_seconds)
                + ((1 - assessment.confidence) * config.safest_unknown_penalty_seconds)
            )
        if cost < 0:
            raise ValueError("risk-aware edge costs must be nonnegative")
        costs[edge_id] = cost
    return costs

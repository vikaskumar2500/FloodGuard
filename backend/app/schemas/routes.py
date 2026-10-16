import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

RouteMode = Literal["FASTEST", "BALANCED", "SAFEST"]
RoutingAlgorithm = Literal["DIJKSTRA", "ASTAR"]


class CoordinateRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    @field_validator("latitude", "longitude")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinate must be finite")
        return value


class RouteCalculationRequest(BaseModel):
    source: CoordinateRequest
    destination: CoordinateRequest
    mode: RouteMode
    algorithm: RoutingAlgorithm = "ASTAR"


class MLRouteMetadata(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    mode: Literal["DISABLED", "SHADOW", "ACTIVE"]
    available: bool
    model_version: str = Field(alias="modelVersion")
    prediction_horizon_minutes: int = Field(default=30, alias="predictionHorizonMinutes")
    provenance_warning: str = Field(
        default="SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.",
        alias="provenanceWarning",
    )


class RouteGeometryResponse(BaseModel):
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]]


class RiskSegmentResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    edge_id: UUID = Field(alias="edgeId")
    risk_score: float = Field(alias="riskScore")
    risk_level: Literal["LOW", "MODERATE", "HIGH", "SEVERE"] = Field(alias="riskLevel")
    confidence: float
    explanation: str
    geometry: RouteGeometryResponse
    ml_probability: float | None = Field(default=None, alias="mlProbability")
    deterministic_risk: float | None = Field(default=None, alias="deterministicRisk")
    fused_risk: float | None = Field(default=None, alias="fusedRisk")


class RouteCalculationResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    route_id: UUID = Field(alias="routeId")
    graph_version_id: UUID = Field(alias="graphVersionId")
    algorithm: RoutingAlgorithm
    mode: RouteMode
    distance_meters: float = Field(alias="distanceMeters")
    estimated_time_seconds: float = Field(alias="estimatedTimeSeconds")
    risk_score: float | None = Field(alias="riskScore")
    risk_level: Literal["LOW", "MODERATE", "HIGH", "SEVERE"] = Field(alias="riskLevel")
    risk_confidence: float = Field(alias="riskConfidence")
    max_edge_risk: float = Field(alias="maxEdgeRisk")
    high_risk_distance_meters: float = Field(alias="highRiskDistanceMeters")
    expanded_nodes: int = Field(alias="expandedNodes")
    risk_model_active: bool = Field(alias="riskModelActive")
    risk_segments: list[RiskSegmentResponse] = Field(alias="riskSegments")
    geometry: RouteGeometryResponse
    ml: MLRouteMetadata | None = Field(default=None, alias="ml")

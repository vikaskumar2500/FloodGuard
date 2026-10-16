from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

type RiskLevel = Literal["LOW", "MODERATE", "HIGH", "SEVERE"]
type RealtimeEventType = Literal[
    "route.created",
    "route.risk_updated",
    "route.invalidated",
    "route.rerouting",
    "route.recalculated",
    "route.reroute_failed",
    "heartbeat",
]


class RiskSegmentData(BaseModel):
    edgeId: str
    riskScore: float
    riskLevel: RiskLevel
    confidence: float
    explanation: str
    geometry: dict[str, object]


class RouteCreatedData(BaseModel):
    riskScore: float
    riskLevel: RiskLevel
    riskConfidence: float


class RouteRiskUpdatedData(BaseModel):
    riskScore: float
    riskLevel: RiskLevel
    riskConfidence: float
    riskSegments: list[RiskSegmentData] = Field(default_factory=list)
    reason: str = "ENVIRONMENT_CHANGED"


class RouteInvalidatedData(RouteRiskUpdatedData):
    affectedEdgeIds: list[str] = Field(default_factory=list)


class RouteReroutingData(BaseModel):
    reason: str


class RouteRecalculatedData(BaseModel):
    oldRouteId: str
    newRouteId: str
    reason: str
    mode: str
    algorithm: str
    oldRiskScore: float
    newRiskScore: float
    oldRiskLevel: RiskLevel
    newRiskLevel: RiskLevel
    oldRiskConfidence: float
    newRiskConfidence: float
    oldEtaSeconds: float
    newEtaSeconds: float
    etaDeltaSeconds: float
    riskReduction: float
    distanceMeters: float
    geometry: dict[str, object]
    riskSegments: list[RiskSegmentData]
    graphVersionId: str
    riskRevision: int


class RouteRerouteFailedData(BaseModel):
    routeId: str
    reason: Literal["NO_ALTERNATIVE", "ROUTING_ERROR", "EXPANSION_LIMIT", "GRAPH_UNAVAILABLE"]
    currentRisk: float
    currentRiskLevel: RiskLevel
    riskConfidence: float
    riskRevision: int
    remainsTraversable: bool


class HeartbeatData(BaseModel):
    status: Literal["connected"] = "connected"


type EventData = (
    RouteCreatedData
    | RouteRiskUpdatedData
    | RouteInvalidatedData
    | RouteReroutingData
    | RouteRecalculatedData
    | RouteRerouteFailedData
    | HeartbeatData
)


class RealtimeEvent(BaseModel):
    eventId: UUID = Field(default_factory=uuid4)
    eventType: RealtimeEventType
    routeId: UUID
    sequence: int = Field(ge=0)
    occurredAt: datetime = Field(default_factory=lambda: datetime.now(UTC))
    riskRevision: int = Field(default=0, ge=0)
    data: EventData

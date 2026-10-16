from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

RiskLevel = Literal["LOW", "MODERATE", "HIGH", "SEVERE"]


@dataclass(frozen=True)
class FloodZoneEvidence:
    score: float
    confidence: float
    severity: str
    evidence_age: timedelta


@dataclass(frozen=True)
class SensorEvidence:
    water_depth_cm: float | None
    rainfall_mm: float | None
    observed_at: datetime
    quality: str


@dataclass(frozen=True)
class WeatherEvidence:
    rainfall_mm: float | None
    observed_at: datetime
    observation_interval_minutes: int | None


@dataclass(frozen=True)
class PredictionEvidence:
    probability: float
    predicted_water_depth_cm: float | None
    predicted_for: datetime
    expires_at: datetime | None


@dataclass(frozen=True)
class IncidentEvidence:
    severity: str
    status: str
    confidence: float | None
    occurred_at: datetime


@dataclass
class EdgeEvidence:
    flood_zones: list[FloodZoneEvidence] = field(default_factory=list)
    sensors: list[SensorEvidence] = field(default_factory=list)
    weather: list[WeatherEvidence] = field(default_factory=list)
    predictions: list[PredictionEvidence] = field(default_factory=list)
    incidents: list[IncidentEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class EdgeRiskAssessment:
    edge_id: UUID
    risk_score: float
    risk_level: RiskLevel
    confidence: float
    flood_zone_score: float
    water_depth_score: float
    rainfall_score: float
    prediction_score: float
    incident_score: float
    evidence_age_seconds: float | None
    explanation: str
    high_risk_distance_m: float


@dataclass(frozen=True)
class RiskSnapshot:
    evaluated_at: datetime
    version: str
    assessments: dict[UUID, EdgeRiskAssessment]

    def for_edge(self, edge_id: UUID) -> EdgeRiskAssessment:
        return self.assessments[edge_id]

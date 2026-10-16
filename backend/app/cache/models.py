from pydantic import BaseModel


class CachedNodeDTO(BaseModel):
    id: str
    coordinate: tuple[float, float]


class CachedEdgeDTO(BaseModel):
    id: str
    source: str
    target: str
    distance_m: float
    base_travel_time_s: float
    geometry: tuple[tuple[float, float], ...]
    speed_limit_mps: float | None = None


class CachedGraphDTO(BaseModel):
    version_id: str
    nodes: list[CachedNodeDTO]
    edges: list[CachedEdgeDTO]


class CachedRiskAssessmentDTO(BaseModel):
    edge_id: str
    risk_score: float
    risk_level: str
    confidence: float
    flood_zone_score: float = 0.0
    water_depth_score: float = 0.0
    rainfall_score: float = 0.0
    prediction_score: float = 0.0
    incident_score: float = 0.0
    evidence_age_seconds: float | None = None
    explanation: str
    high_risk_distance_m: float = 0.0


class CachedRiskSnapshotDTO(BaseModel):
    graph_version_id: str
    risk_revision: int
    version: str
    evaluated_at_iso: str
    assessments: dict[str, CachedRiskAssessmentDTO]


class CachedRouteSegmentDTO(BaseModel):
    edge_id: str
    risk_score: float
    risk_level: str
    confidence: float
    explanation: str
    geometry_coordinates: tuple[tuple[float, float], ...]
    ml_probability: float | None = None
    deterministic_risk: float | None = None
    fused_risk: float | None = None


class CachedRouteTemplateDTO(BaseModel):
    graph_version_id: str
    algorithm: str
    mode: str
    source_node_id: str
    destination_node_id: str
    distance_m: float
    estimated_time_s: float
    risk_score: float
    risk_level: str
    risk_confidence: float
    max_edge_risk: float
    high_risk_distance_m: float
    expanded_nodes: int
    risk_model_active: bool
    edge_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    risk_segments: tuple[CachedRouteSegmentDTO, ...]
    geometry_type: str
    geometry_coordinates: tuple[tuple[float, float], ...]
    risk_revision: int
    ml_mode: str = "DISABLED"
    ml_available: bool = False
    ml_model_version: str = ""

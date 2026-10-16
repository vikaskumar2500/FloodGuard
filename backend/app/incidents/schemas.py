from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class IncidentStatus(StrEnum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class IncidentSeverity(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


class IncidentType(StrEnum):
    WATERLOGGING = "WATERLOGGING"
    FLOODED_ROAD = "FLOODED_ROAD"
    ROAD_BLOCKED = "ROAD_BLOCKED"
    HIGH_WATER = "HIGH_WATER"
    FALLEN_TREE = "FALLEN_TREE"
    ROAD_DAMAGE = "ROAD_DAMAGE"
    OTHER = "OTHER"


class LocationSchema(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class IncidentCreate(BaseModel):
    incident_type: IncidentType
    location: LocationSchema
    description: str
    severity: IncidentSeverity
    occurred_at: datetime
    reporter_user_id: UUID | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class IncidentResponse(BaseModel):
    id: UUID
    incident_type: IncidentType
    location: LocationSchema
    description: str
    severity: IncidentSeverity
    status: IncidentStatus
    confidence: float | None
    occurred_at: datetime
    reported_at: datetime
    verified_at: datetime | None
    attributes: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)

    @field_validator("location", mode="before")
    def convert_location(cls, v):
        if hasattr(v, "data"):  # WKBElement
            from geoalchemy2.shape import to_shape

            shape = to_shape(v)
            return {"latitude": shape.y, "longitude": shape.x}
        return v

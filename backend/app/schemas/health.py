from typing import Literal

from pydantic import BaseModel

HealthStatus = Literal["healthy", "degraded", "unavailable"]


class DependencyHealth(BaseModel):
    status: Literal["healthy", "unavailable"]
    message: str


class HealthResponse(BaseModel):
    status: HealthStatus
    service: str
    version: str
    request_id: str


class ReadinessResponse(HealthResponse):
    ready: bool
    dependencies: dict[str, DependencyHealth]

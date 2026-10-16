from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_rate_limiter, require_permission
from app.core.config import get_settings
from app.db.session import get_session
from app.incidents.clustering import IncidentClustering
from app.incidents.repository import IncidentRepository
from app.incidents.schemas import IncidentCreate, IncidentResponse, LocationSchema
from app.incidents.service import IncidentService
from app.messaging.publisher import EventPublisher, InMemoryEventPublisher
from app.models.user import User
from app.realtime.coordinator import RuntimeRiskState

settings = get_settings()

router = APIRouter(prefix="/incidents", tags=["incidents"])


def get_publisher() -> EventPublisher:
    from app.main import app

    return getattr(app.state, "publisher", InMemoryEventPublisher())


def get_risk_state() -> RuntimeRiskState:
    from app.main import app

    if not hasattr(app.state, "risk_state"):
        app.state.risk_state = RuntimeRiskState()
    return app.state.risk_state


def get_incident_service(
    db: AsyncSession = Depends(get_session),
    publisher: EventPublisher = Depends(get_publisher),
    risk_state: RuntimeRiskState = Depends(get_risk_state),
) -> IncidentService:
    repository = IncidentRepository(db)
    clustering = IncidentClustering(repository)
    return IncidentService(repository, clustering, publisher, risk_state)


@router.post(
    "/",
    response_model=IncidentResponse,
    status_code=201,
    dependencies=[Depends(get_rate_limiter("submit_incident", 10, 60))],
)
async def submit_incident(
    data: IncidentCreate,
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    if not data.reporter_user_id:
        data.reporter_user_id = "ANONYMOUS"  # Fallback actor
    incident = await service.report_incident(data)
    return incident


@router.get("/", response_model=list[IncidentResponse])
async def list_incidents(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    service: IncidentService = Depends(get_incident_service),
) -> Sequence[IncidentResponse]:
    return await service.repository.list_incidents(limit, offset)


@router.get("/nearby", response_model=list[IncidentResponse])
async def list_nearby_incidents(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: float = Query(5000.0, ge=1.0),
    since: datetime | None = None,
    service: IncidentService = Depends(get_incident_service),
) -> Sequence[IncidentResponse]:
    loc = LocationSchema(latitude=lat, longitude=lon)
    return await service.repository.find_nearby(loc, radius, since)


@router.post("/{id}/verify", response_model=IncidentResponse)
async def verify_incident(
    id: UUID,
    current_user: User = Depends(require_permission("update:incidents")),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    incident = await service.verify_incident(id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/{id}/reject", response_model=IncidentResponse)
async def reject_incident(
    id: UUID,
    current_user: User = Depends(require_permission("update:incidents")),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    incident = await service.reject_incident(id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@router.post("/{id}/resolve", response_model=IncidentResponse)
async def resolve_incident(
    id: UUID,
    current_user: User = Depends(require_permission("update:incidents")),
    service: IncidentService = Depends(get_incident_service),
) -> IncidentResponse:
    incident = await service.resolve_incident(id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident

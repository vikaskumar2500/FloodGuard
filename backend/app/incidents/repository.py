from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.incidents.models import Incident
from app.incidents.schemas import IncidentCreate, IncidentStatus, LocationSchema


class IncidentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, data: IncidentCreate) -> Incident:
        point = WKTElement(f"POINT({data.location.longitude} {data.location.latitude})", srid=4326)
        incident = Incident(
            reporter_user_id=data.reporter_user_id,
            incident_type=data.incident_type.value,
            location=point,
            description=data.description,
            severity=data.severity.value,
            occurred_at=data.occurred_at,
            status=IncidentStatus.REPORTED.value,
            attributes=data.attributes,
        )
        self.session.add(incident)
        await self.session.flush()
        return incident

    async def get_by_id(self, incident_id: UUID) -> Incident | None:
        return await self.session.get(Incident, incident_id)

    async def list_incidents(self, limit: int = 50, offset: int = 0) -> Sequence[Incident]:
        stmt = select(Incident).order_by(Incident.reported_at.desc()).limit(limit).offset(offset)
        result = await self.session.scalars(stmt)
        return result.all()

    async def find_nearby(
        self,
        location: LocationSchema,
        radius_meters: float,
        since: datetime | None = None,
    ) -> Sequence[Incident]:
        point = WKTElement(f"POINT({location.longitude} {location.latitude})", srid=4326)
        stmt = select(Incident).where(
            func.ST_DWithin(Incident.location, point, radius_meters, True)
        )
        if since:
            stmt = stmt.where(Incident.occurred_at >= since)
        result = await self.session.scalars(stmt)
        return result.all()

    async def update(self, incident: Incident) -> Incident:
        self.session.add(incident)
        await self.session.flush()
        return incident

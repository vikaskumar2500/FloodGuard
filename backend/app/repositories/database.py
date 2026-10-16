import math
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FloodZone, RoadEdge, RoadNode, RouteSegment, SensorEvent


class RoadNodeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def within_radius(
        self,
        graph_version_id: UUID,
        longitude: float,
        latitude: float,
        radius_m: float,
        limit: int = 100,
    ) -> list[RoadNode]:
        if not (
            math.isfinite(longitude)
            and -180 <= longitude <= 180
            and math.isfinite(latitude)
            and -90 <= latitude <= 90
            and math.isfinite(radius_m)
            and 0 < radius_m <= 100_000
            and 1 <= limit <= 1000
        ):
            raise ValueError("Invalid bounded WGS84 radius query")
        point = cast(func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326), Geography)
        location = cast(RoadNode.location, Geography)
        query = (
            select(RoadNode)
            .where(
                RoadNode.graph_version_id == graph_version_id,
                func.ST_DWithin(location, point, radius_m),
            )
            .order_by(func.ST_Distance(location, point), RoadNode.id)
            .limit(limit)
        )
        return list((await self.session.scalars(query)).all())


class FloodZoneRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def intersecting_edge(self, edge_id: UUID) -> list[FloodZone]:
        query = (
            select(FloodZone)
            .join(RoadEdge, func.ST_Intersects(FloodZone.geometry, RoadEdge.geometry))
            .where(RoadEdge.id == edge_id)
            .order_by(FloodZone.id)
        )
        return list((await self.session.scalars(query)).all())


class SensorEventRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def insert_if_new(self, values: dict) -> UUID | None:
        """Return the inserted ID or None for an existing producer/source identity.

        This stores no downstream effects. Future ingestion must also compare payloads
        for conflicting identity reuse and atomically write its outbox.
        """
        statement = (
            insert(SensorEvent)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=[SensorEvent.producer, SensorEvent.external_event_id]
            )
            .returning(SensorEvent.id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none()


class RouteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ordered_segments(self, route_id: UUID) -> list[RouteSegment]:
        return list(
            (
                await self.session.scalars(
                    select(RouteSegment)
                    .where(RouteSegment.route_id == route_id)
                    .order_by(RouteSegment.sequence)
                )
            ).all()
        )

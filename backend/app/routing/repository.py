import json
import math
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GraphVersion, Region, RoadEdge, RoadNode

from .models import RoutingEdge, RoutingGraph, RoutingNode


class RoutingGraphRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_graph_version(
        self,
        source_longitude: float,
        source_latitude: float,
        destination_longitude: float,
        destination_latitude: float,
    ) -> GraphVersion | None:
        source = func.ST_SetSRID(func.ST_MakePoint(source_longitude, source_latitude), 4326)
        destination = func.ST_SetSRID(
            func.ST_MakePoint(destination_longitude, destination_latitude), 4326
        )
        query = (
            select(GraphVersion)
            .join(Region, Region.id == GraphVersion.region_id)
            .where(
                func.ST_Covers(Region.geometry, source),
                func.ST_Covers(Region.geometry, destination),
            )
            .order_by(GraphVersion.version.desc(), GraphVersion.id)
            .limit(1)
        )
        return await self.session.scalar(query)

    async def nearest_node(
        self,
        graph_version_id: UUID,
        longitude: float,
        latitude: float,
        radius_m: float,
    ) -> tuple[UUID, float] | None:
        point = cast(func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326), Geography)
        location = cast(RoadNode.location, Geography)
        distance = func.ST_Distance(location, point)
        query = (
            select(RoadNode.id, distance)
            .where(
                RoadNode.graph_version_id == graph_version_id,
                func.ST_DWithin(location, point, radius_m),
            )
            .order_by(distance, RoadNode.id)
            .limit(1)
        )
        row = (await self.session.execute(query)).first()
        return (row[0], float(row[1])) if row else None

    async def load_graph(self, graph_version_id: UUID) -> RoutingGraph:
        graph = RoutingGraph()
        node_query = select(
            RoadNode.id,
            func.ST_X(RoadNode.location),
            func.ST_Y(RoadNode.location),
        ).where(RoadNode.graph_version_id == graph_version_id)
        for node_id, longitude, latitude in (await self.session.execute(node_query)).all():
            graph.add_node(RoutingNode(node_id, (float(longitude), float(latitude))))

        edge_query = select(
            RoadEdge.id,
            RoadEdge.source_node_id,
            RoadEdge.target_node_id,
            RoadEdge.distance_m,
            RoadEdge.base_travel_time_s,
            RoadEdge.speed_limit_kph,
            func.ST_AsGeoJSON(RoadEdge.geometry),
        ).where(RoadEdge.graph_version_id == graph_version_id)
        for edge_id, source, target, distance, travel_time, speed, geometry_json in (
            await self.session.execute(edge_query)
        ).all():
            geometry = json.loads(geometry_json)
            coordinates = tuple(
                (float(coordinate[0]), float(coordinate[1]))
                for coordinate in geometry["coordinates"]
            )
            graph.add_edge(
                RoutingEdge(
                    edge_id,
                    source,
                    target,
                    float(distance),
                    float(travel_time),
                    coordinates,
                    None if speed is None else float(speed) / 3.6,
                )
            )
        graph.validate()
        return graph


def validate_coordinate(longitude: float, latitude: float) -> None:
    if not (
        math.isfinite(longitude)
        and -180 <= longitude <= 180
        and math.isfinite(latitude)
        and -90 <= latitude <= 90
    ):
        raise ValueError("invalid WGS84 coordinate")

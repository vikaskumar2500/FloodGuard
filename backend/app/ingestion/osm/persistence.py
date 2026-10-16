from hashlib import sha256
from uuid import uuid4

from geoalchemy2 import WKTElement
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GraphVersion, Region, RoadEdge, RoadNode

from .models import ImportGraph


class DuplicateImportError(ValueError):
    pass


def source_checksum(path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def polygon_wkt(boundary: tuple[tuple[float, float], ...]) -> WKTElement:
    coordinates = ",".join(f"{longitude} {latitude}" for longitude, latitude in boundary)
    return WKTElement(f"MULTIPOLYGON((({coordinates})))", srid=4326)


def line_wkt(coordinates: tuple[tuple[float, float], ...]) -> WKTElement:
    values = ",".join(f"{longitude} {latitude}" for longitude, latitude in coordinates)
    return WKTElement(f"LINESTRING({values})", srid=4326)


def multipoint_wkt(coordinates: tuple[tuple[float, float], ...]) -> WKTElement:
    values = ",".join(f"({longitude} {latitude})" for longitude, latitude in coordinates)
    return WKTElement(f"MULTIPOINT({values})", srid=4326)


async def persist_graph(
    session: AsyncSession,
    *,
    graph: ImportGraph,
    region_slug: str,
    region_name: str,
    source: str,
    source_sha256: str,
    requested_version: int | None = None,
) -> GraphVersion:
    region = await session.scalar(select(Region).where(Region.slug == region_slug))
    if region is None:
        region = Region(slug=region_slug, name=region_name, geometry=polygon_wkt(graph.boundary))
        session.add(region)
        await session.flush()
    elif not await session.scalar(
        select(
            func.ST_Covers(
                Region.geometry,
                multipoint_wkt(tuple(node.coordinate for node in graph.nodes)),
            )
        ).where(Region.id == region.id)
    ):
        raise ValueError("OSM graph contains nodes outside the existing region boundary")
    versions = list(
        (
            await session.scalars(
                select(GraphVersion)
                .where(GraphVersion.region_id == region.id)
                .order_by(GraphVersion.version)
            )
        ).all()
    )
    if any(version.attributes.get("source_sha256") == source_sha256 for version in versions):
        raise DuplicateImportError("this source file was already imported for the region")
    if requested_version is not None and requested_version <= 0:
        raise ValueError("graph version must be positive")
    version_number = requested_version or (
        max((version.version for version in versions), default=0) + 1
    )
    if any(version.version == version_number for version in versions):
        raise DuplicateImportError(
            f"graph version {version_number} already exists for {region_slug}"
        )
    graph_version = GraphVersion(
        region_id=region.id,
        version=version_number,
        source=source,
        attributes={"source_sha256": source_sha256, "format": "osm-xml", "phase": 4},
    )
    session.add(graph_version)
    await session.flush()
    node_ids = {node.osm_id: uuid4() for node in graph.nodes}
    batch_size = 2000
    for i in range(0, len(graph.nodes), batch_size):
        node_batch = [
            RoadNode(
                id=node_ids[node.osm_id],
                graph_version_id=graph_version.id,
                osm_node_id=node.osm_id,
                location=WKTElement(f"POINT({node.coordinate[0]} {node.coordinate[1]})", srid=4326),
                attributes=node.metadata,
            )
            for node in graph.nodes[i : i + batch_size]
        ]
        session.add_all(node_batch)
        await session.flush()
        for node_obj in node_batch:
            session.expunge(node_obj)

    for i in range(0, len(graph.edges), batch_size):
        edge_batch = [
            RoadEdge(
                graph_version_id=graph_version.id,
                osm_way_id=edge.osm_way_id,
                osm_segment_index=edge.segment_index,
                osm_direction=edge.direction,
                source_node_id=node_ids[edge.source_osm_node_id],
                target_node_id=node_ids[edge.target_osm_node_id],
                geometry=line_wkt(edge.coordinates),
                distance_m=edge.distance_m,
                base_travel_time_s=edge.base_travel_time_s,
                road_class=edge.road_class,
                speed_limit_kph=edge.speed_limit_kph,
                is_one_way=edge.is_one_way,
                attributes=edge.metadata,
            )
            for edge in graph.edges[i : i + batch_size]
        ]
        session.add_all(edge_batch)
        await session.flush()
        for edge_obj in edge_batch:
            session.expunge(edge_obj)

    return graph_version

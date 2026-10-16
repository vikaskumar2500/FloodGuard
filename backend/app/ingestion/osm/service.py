from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from .graph_builder import build_graph
from .models import ImportGraph
from .parser import parse_osm_xml
from .persistence import persist_graph, source_checksum
from .validator import validate_graph


def load_graph(path: Path) -> tuple[ImportGraph, str]:
    nodes, ways, _ = parse_osm_xml(path)
    graph = build_graph(nodes, ways)
    validate_graph(graph)
    return graph, source_checksum(path)


async def ingest_osm(
    session: AsyncSession,
    *,
    path: Path,
    region_slug: str,
    region_name: str,
    graph_version: int | None = None,
):
    graph, checksum = load_graph(path)
    version = await persist_graph(
        session,
        graph=graph,
        region_slug=region_slug,
        region_name=region_name,
        source=path.name,
        source_sha256=checksum,
        requested_version=graph_version,
    )
    return version, graph, checksum

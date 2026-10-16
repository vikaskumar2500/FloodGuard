import argparse
import asyncio
import json
from pathlib import Path

from app.core.config import Settings
from app.db.session import Database

from .persistence import DuplicateImportError
from .service import ingest_osm, load_graph


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Ingest a local OpenStreetMap XML extract")
    command.add_argument("--region", required=True, help="existing or new region slug")
    command.add_argument("--name", help="region display name; defaults to the slug")
    command.add_argument("--file", required=True, type=Path, help="local .osm XML file")
    command.add_argument("--graph-version", type=int)
    command.add_argument("--dry-run", action="store_true")
    return command


def summary(region: str, source: str, version: int | None, graph) -> dict:
    stats = graph.stats
    return {
        "region": region,
        "graph_version": version,
        "source": source,
        "osm_nodes_read": stats.osm_nodes_read,
        "osm_ways_read": stats.osm_ways_read,
        "accepted_road_ways": stats.accepted_road_ways,
        "excluded_road_ways": stats.excluded_road_ways,
        "restricted_roads_skipped": stats.restricted_roads_skipped,
        "graph_nodes": len(graph.nodes),
        "directed_edges": len(graph.edges),
        "one_way_ways": stats.one_way_ways,
        "two_way_ways": stats.two_way_ways,
        "invalid_segments_skipped": stats.invalid_segments_skipped,
        "malformed_speed_tags": stats.malformed_speed_tags,
        "total_distance_m": round(stats.total_distance_m, 2),
        "weakly_connected_components": stats.weakly_connected_components,
        "largest_component_percent": round(stats.largest_component_percent, 2),
    }


async def run(args: argparse.Namespace) -> None:
    if args.dry_run:
        graph, checksum = load_graph(args.file)
        payload = {
            **summary(args.region, args.file.name, args.graph_version, graph),
            "sha256": checksum,
        }
        print(json.dumps(payload, indent=2))
        return
    database = Database(Settings())
    try:
        async with database.sessions() as session, session.begin():
            version, graph, checksum = await ingest_osm(
                session,
                path=args.file,
                region_slug=args.region,
                region_name=args.name or args.region.replace("-", " ").title(),
                graph_version=args.graph_version,
            )
        payload = {
            **summary(args.region, args.file.name, version.version, graph),
            "sha256": checksum,
        }
        print(json.dumps(payload, indent=2))
    finally:
        await database.close()


def main() -> None:
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except (DuplicateImportError, FileNotFoundError, ValueError) as error:
        raise SystemExit(f"ingest-osm failed: {error}") from error


if __name__ == "__main__":
    main()

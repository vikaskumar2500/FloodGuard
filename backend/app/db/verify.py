"""Read-only catalog/fixture verification; EXPLAIN changes are transaction-local."""

import asyncio
import json

from geoalchemy2 import Geometry
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.base import Base
from app.db.seed import EDGE_PAIRS, POINTS, seed_id
from app.db.session import Database
from app.models import (
    FloodPrediction,
    FloodZone,
    GraphVersion,
    Incident,
    Region,
    RoadEdge,
    RoadNode,
    Route,
    RouteSegment,
    SensorEvent,
    User,
    WeatherObservation,
)
from app.repositories.database import FloodZoneRepository, RoadNodeRepository, RouteRepository

SEED_ROWS = {
    User: ["user"],
    Region: ["region"],
    GraphVersion: ["graph"],
    RoadNode: [f"node-{name}" for name in POINTS],
    RoadEdge: [f"edge-{source}{target}" for source, target in EDGE_PAIRS],
    FloodZone: ["zone"],
    SensorEvent: ["sensor"],
    WeatherObservation: ["weather"],
    FloodPrediction: ["prediction"],
    Incident: ["incident"],
    Route: ["route"],
    RouteSegment: ["segment-0", "segment-1"],
}


def require(condition: bool, message: str):
    if not condition:
        raise RuntimeError(message)


async def verify(session: AsyncSession) -> dict:
    require((await session.execute(text("SELECT 1"))).scalar_one() == 1, "Database unreachable")
    version = (await session.execute(text("SELECT PostGIS_Version()"))).scalar_one()
    tables = set(
        (
            await session.scalars(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        ).all()
    )
    require(set(Base.metadata.tables) <= tables, "Missing domain tables; run Alembic upgrade head")
    revision = (await session.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    require(
        revision in ScriptDirectory.from_config(Config("alembic.ini")).get_heads(),
        "Database revision is behind Alembic head",
    )
    constraints = set(
        (
            await session.scalars(
                text(
                    "SELECT conname FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid=c.connamespace "
                    "WHERE n.nspname='public' AND c.convalidated"
                )
            )
        ).all()
    )
    expected_constraints = {
        str(c.name) for t in Base.metadata.tables.values() for c in t.constraints
    }
    require(expected_constraints <= constraints, "Missing or unvalidated database constraints")
    indexes = set(
        (
            await session.scalars(
                text(
                    "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND i.indisvalid AND i.indisready"
                )
            )
        ).all()
    )
    expected_indexes = {str(i.name) for t in Base.metadata.tables.values() for i in t.indexes}
    require(expected_indexes <= indexes, "Missing or invalid indexes")
    triggers = set(
        (
            await session.scalars(
                text(
                    "SELECT tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND NOT t.tgisinternal AND t.tgenabled='O'"
                )
            )
        ).all()
    )
    require(
        {f"trg_{name}_updated_at" for name in ("users", "flood_zones", "incidents")} <= triggers,
        "Missing or disabled updated_at triggers",
    )
    actual_spatial = {
        (r[0], r[1]): (r[2], r[3])
        for r in (
            await session.execute(
                text(
                    "SELECT c.relname,a.attname,postgis_typmod_srid(a.atttypmod), "
                    "upper(postgis_typmod_type(a.atttypmod)) "
                    "FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND a.atttypid='geometry'::regtype "
                    "AND a.attnum > 0 AND NOT a.attisdropped AND c.relkind='r'"
                )
            )
        ).all()
    }
    expected_spatial = {
        (t.name, c.name): (c.type.srid, c.type.geometry_type)
        for t in Base.metadata.tables.values()
        for c in t.columns
        if isinstance(c.type, Geometry)
    }
    spatial_mismatches = {
        f"{key[0]}.{key[1]}": {"actual": actual_spatial.get(key), "expected": value}
        for key, value in expected_spatial.items()
        if actual_spatial.get(key) != value
    }
    require(not spatial_mismatches, f"Spatial type/SRID mismatch: {spatial_mismatches}")
    seed_counts = {}
    for model, names in SEED_ROWS.items():
        count = (
            await session.execute(
                select(func.count())
                .select_from(model)
                .where(model.id.in_([seed_id(name) for name in names]))
            )
        ).scalar_one()
        require(count == len(names), f"Missing synthetic seed rows in {model.__tablename__}")
        seed_counts[model.__tablename__] = count
    nearby = await RoadNodeRepository(session).within_radius(seed_id("graph"), 72.877, 19.076, 150)
    require(len(nearby) == 3, "Unexpected seeded meter-radius result")
    zones = await FloodZoneRepository(session).intersecting_edge(seed_id("edge-AB"))
    require(seed_id("zone") in {z.id for z in zones}, "Seeded road/zone intersection failed")
    contains = (
        await session.execute(
            text(
                "SELECT ST_Covers(geometry, ST_SetSRID(ST_MakePoint(72.8775,19.076),4326)) "
                "FROM flood_zones WHERE id=:id"
            ),
            {"id": seed_id("zone")},
        )
    ).scalar_one()
    require(contains is True, "Seeded point containment failed")
    segments = await RouteRepository(session).ordered_segments(seed_id("route"))
    require([s.sequence for s in segments] == [0, 1], "Invalid seeded segment ordering")
    require(
        [s.road_edge_id for s in segments] == [seed_id("edge-AB"), seed_id("edge-BD")],
        "Invalid seeded route/edge association",
    )
    explain_query = (
        "EXPLAIN (ANALYZE, BUFFERS) SELECT id FROM road_nodes "
        "WHERE ST_DWithin(location::geography, "
        "ST_SetSRID(ST_MakePoint(72.877,19.076),4326)::geography,150)"
    )
    natural_plan = list((await session.scalars(text(explain_query))).all())
    # A nested transaction restores planner settings and never commits caller work.
    async with session.begin_nested() as savepoint:
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        index_plan = list((await session.scalars(text(explain_query))).all())
        await savepoint.rollback()
    require(
        any("ix_road_nodes_location_geography" in line for line in index_plan),
        "Meter-radius query cannot use expected GiST expression index",
    )
    return {
        "status": "passed",
        "postgis": version,
        "revision": revision,
        "tables": len(Base.metadata.tables),
        "constraints": len(expected_constraints),
        "indexes": len(expected_indexes),
        "spatial_columns": len(expected_spatial),
        "seed_rows": seed_counts,
        "nearby_nodes": len(nearby),
        "road_zone_intersection": True,
        "point_containment": True,
        "segment_sequences": [s.sequence for s in segments],
        "natural_plan": natural_plan,
        "index_eligibility_plan": index_plan,
        "performance_claim": (
            "Structural index eligibility only; tiny synthetic data is not a benchmark"
        ),
    }


async def main():
    database = Database(Settings())
    try:
        async with database.sessions() as session:
            print(json.dumps(await verify(session), indent=2, sort_keys=True))
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())

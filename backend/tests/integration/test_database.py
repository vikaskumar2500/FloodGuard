"""Real PostGIS tests: create/drop only databases minted by this test process."""

from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic.config import Config
from geoalchemy2 import WKTElement
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.core.config import Settings
from app.db.base import Base
from app.db.seed import SEED_TIME, point, seed, seed_id
from app.db.verify import verify
from app.ingestion.osm.persistence import DuplicateImportError, persist_graph, source_checksum
from app.ingestion.osm.service import load_graph
from app.models import (
    FloodPrediction,
    FloodZone,
    GraphVersion,
    Incident,
    RoadEdge,
    RoadNode,
    Route,
    RouteSegment,
    SensorEvent,
    User,
    WeatherObservation,
)
from app.repositories.database import (
    FloodZoneRepository,
    RoadNodeRepository,
    RouteRepository,
    SensorEventRepository,
)
from app.routing.service import calculate_route

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[2]


async def migrate(engine, action, target=None):
    def run(connection):
        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.attributes["connection"] = connection
        if target is None:
            action(config)
        else:
            action(config, target)

    async with engine.begin() as connection:
        await connection.run_sync(run)


@asynccontextmanager
async def fresh_database():
    # Never honor an arbitrary destructive-test database name from the environment.
    name = "floodguard_test_" + uuid4().hex
    url = make_url(Settings().database_url.get_secret_value())
    admin = create_async_engine(
        url.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    engine = None
    created = False
    try:
        async with admin.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{name}" TEMPLATE template0'))
            created = True
        engine = create_async_engine(url.set(database=name), poolclass=NullPool)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        if created:
            async with admin.connect() as connection:
                await connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        await admin.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def migrated_engine():
    async with fresh_database() as engine:
        await migrate(engine, command.upgrade, "head")
        yield engine


@pytest_asyncio.fixture
async def seeded_session(migrated_engine):
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        async with session.begin():
            await seed(session)
            yield session
            await session.rollback()


async def test_migration_fresh_database_and_round_trip():
    async with fresh_database() as engine:
        async with engine.connect() as connection:
            assert (
                await connection.execute(
                    text("SELECT count(*) FROM pg_extension WHERE extname='postgis'")
                )
            ).scalar_one() == 0
        await migrate(engine, command.upgrade, "head")
        async with engine.connect() as connection:
            assert set(
                (await connection.scalars(text("SELECT extname FROM pg_extension"))).all()
            ) == {"plpgsql", "postgis"}
        async with AsyncSession(engine) as session, session.begin():
            await seed(session)
            assert (await verify(session))["status"] == "passed"
        await migrate(engine, command.downgrade, "base")
        async with engine.connect() as connection:
            tables = set(
                (
                    await connection.scalars(
                        text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
                    )
                ).all()
            )
            assert not tables.intersection(Base.metadata.tables)
            assert (
                await connection.execute(
                    text("SELECT count(*) FROM pg_proc WHERE proname='floodguard_set_updated_at'")
                )
            ).scalar_one() == 0
            assert (await connection.execute(text("SELECT PostGIS_Version()"))).scalar_one()
        await migrate(engine, command.upgrade, "head")
        await migrate(engine, command.check)
        async with AsyncSession(engine) as session, session.begin():
            await seed(session)
            assert (await verify(session))["tables"] == 12


async def test_seed_repeatable_and_spatial_catalog(seeded_session):
    before = await verify(seeded_session)
    assert sum(before["seed_rows"].values()) == 23
    assert all(count == 0 for count in (await seed(seeded_session)).values())
    after = await verify(seeded_session)
    assert after["seed_rows"] == before["seed_rows"]
    assert after["spatial_columns"] == 11


async def test_osm_fixture_persists_directed_postgis_graph(migrated_engine):
    fixture = BACKEND_ROOT / "tests" / "fixtures" / "tiny.osm"
    graph, checksum = load_graph(fixture)
    async with AsyncSession(migrated_engine) as session, session.begin():
        version = await persist_graph(
            session,
            graph=graph,
            region_slug="fixture-region",
            region_name="Fixture region",
            source=fixture.name,
            source_sha256=checksum,
        )
        assert (
            await session.execute(
                text("SELECT count(*) FROM road_nodes WHERE graph_version_id = :id"),
                {"id": version.id},
            )
        ).scalar_one() == 8
        assert (
            await session.execute(
                text("SELECT count(*) FROM road_edges WHERE graph_version_id = :id"),
                {"id": version.id},
            )
        ).scalar_one() == 12
        assert (
            await session.execute(
                text(
                    "SELECT count(*) FROM road_edges "
                    "WHERE graph_version_id = :id AND osm_direction = -1"
                ),
                {"id": version.id},
            )
        ).scalar_one() == 5
        assert (
            await session.execute(
                text(
                    "SELECT bool_and(ST_SRID(geometry) = 4326 AND distance_m > 0 "
                    "AND base_travel_time_s > 0) FROM road_edges WHERE graph_version_id = :id"
                ),
                {"id": version.id},
            )
        ).scalar_one()
        with pytest.raises(DuplicateImportError):
            await persist_graph(
                session,
                graph=graph,
                region_slug="fixture-region",
                region_name="Fixture region",
                source=fixture.name,
                source_sha256=source_checksum(fixture),
            )


async def test_route_calculation_loads_one_graph_and_persists_segments(migrated_engine):
    fixture = BACKEND_ROOT / "tests" / "fixtures" / "tiny.osm"
    graph, checksum = load_graph(fixture)
    settings = Settings(_env_file=None, app_env="test")
    async with AsyncSession(migrated_engine, expire_on_commit=False) as session:
        async with session.begin():
            version = await persist_graph(
                session,
                graph=graph,
                region_slug="routing-fixture-region",
                region_name="Routing fixture region",
                source=fixture.name,
                source_sha256=checksum,
            )
            result = await calculate_route(
                session,
                source=(0.0, 0.0),
                destination=(0.003, 0.001),
                mode="FASTEST",
                algorithm="ASTAR",
                settings=settings,
            )
            segments = list(
                (
                    await session.scalars(
                        select(RouteSegment)
                        .where(RouteSegment.route_id == result.route_id)
                        .order_by(RouteSegment.sequence)
                    )
                ).all()
            )
            route = await session.get(Route, result.route_id)
            assert result.graph_version_id == version.id
            assert result.risk_score is None
            assert result.distance_m > 0
            assert result.estimated_time_s > 0
            assert result.geometry_type == "LineString"
            assert segments
            assert [segment.sequence for segment in segments] == list(range(len(segments)))
            assert all(segment.graph_version_id == version.id for segment in segments)
            assert route is not None and route.risk_score is None


async def test_road_node_insertion_and_nullable_osm(seeded_session):
    node = RoadNode(graph_version_id=seed_id("graph"), location=point("A"))
    seeded_session.add(node)
    await seeded_session.flush()
    assert node.id and node.osm_node_id is None and node.created_at.tzinfo is not None
    assert (
        await seeded_session.execute(
            select(func.ST_SRID(RoadNode.location)).where(RoadNode.id == node.id)
        )
    ).scalar_one() == 4326


@pytest.mark.parametrize("column", ["source_node_id", "target_node_id"])
async def test_edge_missing_node_foreign_keys(seeded_session, column):
    with pytest.raises(IntegrityError, match="fk_road_edges_"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RoadEdge).where(RoadEdge.id == seed_id("edge-AB")).values({column: uuid4()})
            )


async def test_graph_compatibility_for_edges_and_segments(seeded_session):
    graph = GraphVersion(region_id=seed_id("region"), version=2, source="SYNTHETIC")
    seeded_session.add(graph)
    await seeded_session.flush()
    node = RoadNode(graph_version_id=graph.id, location=point("A"))
    seeded_session.add(node)
    await seeded_session.flush()
    with pytest.raises(IntegrityError, match="fk_road_edges_source_graph"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RoadEdge)
                .where(RoadEdge.id == seed_id("edge-AB"))
                .values(source_node_id=node.id)
            )
    with pytest.raises(IntegrityError, match="fk_route_segments_"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RouteSegment)
                .where(RouteSegment.id == seed_id("segment-0"))
                .values(graph_version_id=graph.id)
            )


@pytest.mark.parametrize(
    "model,name,column,value,constraint",
    [
        (FloodPrediction, "prediction", "probability", -0.1, "probability_range"),
        (FloodPrediction, "prediction", "probability", 1.1, "probability_range"),
        (FloodPrediction, "prediction", "probability", float("nan"), "probability_range"),
        (FloodPrediction, "prediction", "predicted_water_depth_cm", -1, "nonnegative"),
        (FloodPrediction, "prediction", "prediction_horizon_minutes", 0, "horizon_positive"),
        (FloodPrediction, "prediction", "model_version", "", "lineage_nonempty"),
        (RoadEdge, "edge-AB", "distance_m", -1, "distance_m_nonnegative"),
        (RoadEdge, "edge-AB", "distance_m", float("inf"), "distance_m_nonnegative"),
        (RoadEdge, "edge-AB", "base_travel_time_s", -1, "base_travel_time_s_nonnegative"),
        (RoadEdge, "edge-AB", "speed_limit_kph", 0, "speed_positive"),
        (RoadEdge, "edge-AB", "source_node_id", seed_id("node-B"), "distinct_nodes"),
        (FloodZone, "zone", "risk_score", 1.1, "risk_score_range"),
        (FloodZone, "zone", "confidence", -0.1, "confidence_range"),
        (FloodZone, "zone", "valid_until", SEED_TIME, "validity_order"),
        (SensorEvent, "sensor", "water_depth_cm", -1, "nonnegative"),
        (SensorEvent, "sensor", "external_event_id", "", "identity_nonempty"),
        (WeatherObservation, "weather", "humidity_percent", 101, "humidity_range"),
        (WeatherObservation, "weather", "rainfall_mm", -1, "nonnegative"),
        (WeatherObservation, "weather", "wind_speed_mps", -1, "nonnegative"),
        (Route, "route", "risk_score", 2, "risk_score_range"),
        (Route, "route", "estimated_time_s", -1, "nonnegative"),
        (Route, "route", "expires_at", SEED_TIME, "expiry_order"),
        (RouteSegment, "segment-0", "sequence", -1, "sequence_nonnegative"),
        (Incident, "incident", "status", "UNKNOWN", "status_values"),
        (User, "user", "email", "UPPER@example.test", "email_normalized"),
        (User, "user", "role", "ROOT", "role_values"),
    ],
)
async def test_invalid_values_rejected(seeded_session, model, name, column, value, constraint):
    with pytest.raises(IntegrityError, match=constraint):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(model).where(model.id == seed_id(name)).values({column: value})
            )


async def test_unique_email(seeded_session):
    with pytest.raises(IntegrityError, match="uq_users_email"):
        async with seeded_session.begin_nested():
            seeded_session.add(User(email="seed.operator@example.test", display_name="Duplicate"))
            await seeded_session.flush()


async def test_osm_node_identity_is_graph_scoped(seeded_session):
    await seeded_session.execute(
        update(RoadNode).where(RoadNode.id == seed_id("node-A")).values(osm_node_id=12345)
    )
    with pytest.raises(IntegrityError, match="uq_road_nodes_graph_version_id"):
        async with seeded_session.begin_nested():
            seeded_session.add(
                RoadNode(graph_version_id=seed_id("graph"), osm_node_id=12345, location=point("B"))
            )
            await seeded_session.flush()
    graph = GraphVersion(region_id=seed_id("region"), version=2, source="SYNTHETIC")
    seeded_session.add(graph)
    await seeded_session.flush()
    seeded_session.add(RoadNode(graph_version_id=graph.id, osm_node_id=12345, location=point("A")))
    await seeded_session.flush()


async def test_route_segment_order_uniqueness(seeded_session):
    with pytest.raises(IntegrityError, match="uq_route_segments_route_id"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RouteSegment)
                .where(RouteSegment.id == seed_id("segment-1"))
                .values(sequence=0)
            )


async def test_sensor_deduplication_constraint_and_repository(seeded_session):
    event = await seeded_session.get(SensorEvent, seed_id("sensor"))
    values = {
        c.key: getattr(event, c.key)
        for c in SensorEvent.__table__.columns
        if c.key not in {"id", "metadata"}
    }
    repo = SensorEventRepository(seeded_session)
    assert await repo.insert_if_new(values) is None
    values["producer"] = "different-producer"
    assert await repo.insert_if_new(values) is not None
    with pytest.raises(IntegrityError, match="uq_sensor_events_producer"):
        async with seeded_session.begin_nested():
            seeded_session.add(SensorEvent(**{**values, "producer": event.producer}))
            await seeded_session.flush()


async def test_weather_deduplication(seeded_session):
    row = await seeded_session.get(WeatherObservation, seed_id("weather"))
    values = {
        c.key: getattr(row, c.key) for c in WeatherObservation.__table__.columns if c.key != "id"
    }
    with pytest.raises(IntegrityError, match="uq_weather_observations_provider"):
        async with seeded_session.begin_nested():
            seeded_session.add(WeatherObservation(**values))
            await seeded_session.flush()


async def test_spatial_queries_and_ordered_segments(seeded_session):
    nodes = await RoadNodeRepository(seeded_session).within_radius(
        seed_id("graph"), 72.877, 19.076, 150
    )
    assert nodes[0].id == seed_id("node-A")
    assert {n.id for n in nodes} == {seed_id("node-A"), seed_id("node-B"), seed_id("node-C")}
    assert any(
        z.id == seed_id("zone")
        for z in await FloodZoneRepository(seeded_session).intersecting_edge(seed_id("edge-AB"))
    )
    assert [
        s.sequence for s in await RouteRepository(seeded_session).ordered_segments(seed_id("route"))
    ] == [0, 1]


async def test_geometry_srid_bounds_and_prediction_target(seeded_session):
    with pytest.raises(DBAPIError, match="SRID"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RoadNode)
                .where(RoadNode.id == seed_id("node-A"))
                .values(location=WKTElement("POINT(0 0)", srid=3857))
            )
    with pytest.raises(IntegrityError, match="valid_wgs84"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RoadNode)
                .where(RoadNode.id == seed_id("node-A"))
                .values(location=WKTElement("POINT(181 0)", srid=4326))
            )
    with pytest.raises(IntegrityError, match="target_required"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(FloodPrediction).values(geometry=None, road_edge_id=None)
            )
    # Location-only and edge-only prediction targets are both valid.
    await seeded_session.execute(update(FloodPrediction).values(geometry=None))
    await seeded_session.execute(
        update(FloodPrediction).values(geometry=point("A"), road_edge_id=None)
    )


async def test_delete_cascades_restrictions_and_user_anonymization(seeded_session):
    with pytest.raises(IntegrityError, match="fk_"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(delete(RoadNode).where(RoadNode.id == seed_id("node-A")))
    with pytest.raises(IntegrityError, match="fk_"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(delete(RoadEdge).where(RoadEdge.id == seed_id("edge-AB")))
    await seeded_session.execute(delete(User).where(User.id == seed_id("user")))
    assert (await seeded_session.scalar(select(Route.user_id))) is None
    assert (await seeded_session.scalar(select(Incident.reporter_user_id))) is None
    await seeded_session.execute(delete(Route).where(Route.id == seed_id("route")))
    assert (await seeded_session.scalar(select(func.count()).select_from(RouteSegment))) == 0
    assert (await seeded_session.scalar(select(func.count()).select_from(RoadEdge))) == 8


async def test_updated_at_trigger_for_raw_sql(seeded_session):
    before = await seeded_session.scalar(select(User.updated_at))
    await seeded_session.execute(text("UPDATE users SET display_name='Updated synthetic operator'"))
    after = await seeded_session.scalar(select(User.updated_at))
    assert after > before
    assert (await seeded_session.scalar(select(User.created_at))) == SEED_TIME


async def test_verified_timestamp_order(seeded_session):
    with pytest.raises(IntegrityError, match="verification_order"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(Incident).values(verified_at=SEED_TIME - timedelta(seconds=1))
            )


async def test_prediction_multipolygon_and_rejected_line_target(seeded_session):
    polygon = await seeded_session.scalar(select(FloodZone.geometry))
    await seeded_session.execute(
        update(FloodPrediction).values(geometry=polygon, road_edge_id=None)
    )
    assert (
        await seeded_session.scalar(select(func.GeometryType(FloodPrediction.geometry)))
        == "MULTIPOLYGON"
    )
    with pytest.raises(IntegrityError, match="geometry_type"):
        async with seeded_session.begin_nested():
            geometry = await seeded_session.scalar(select(RoadEdge.geometry).limit(1))
            await seeded_session.execute(update(FloodPrediction).values(geometry=geometry))


async def test_osm_way_segment_direction_identity(seeded_session):
    await seeded_session.execute(
        update(RoadEdge)
        .where(RoadEdge.id == seed_id("edge-AB"))
        .values(osm_way_id=42, osm_segment_index=0, osm_direction=1)
    )
    await seeded_session.execute(
        update(RoadEdge)
        .where(RoadEdge.id == seed_id("edge-BA"))
        .values(osm_way_id=42, osm_segment_index=0, osm_direction=-1)
    )
    with pytest.raises(IntegrityError, match="uq_road_edges_graph_version_id"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RoadEdge)
                .where(RoadEdge.id == seed_id("edge-AC"))
                .values(osm_way_id=42, osm_segment_index=0, osm_direction=1)
            )
    with pytest.raises(IntegrityError, match="osm_identity_complete"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RoadEdge).where(RoadEdge.id == seed_id("edge-CD")).values(osm_way_id=42)
            )


async def test_empty_and_invalid_geometry_rejected(seeded_session):
    with pytest.raises(IntegrityError, match="valid_wgs84"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(RoadNode)
                .where(RoadNode.id == seed_id("node-A"))
                .values(location=WKTElement("POINT EMPTY", srid=4326))
            )
    with pytest.raises(IntegrityError, match="valid_wgs84"):
        async with seeded_session.begin_nested():
            await seeded_session.execute(
                update(FloodZone).values(
                    geometry=WKTElement("MULTIPOLYGON(((0 0,1 1,1 0,0 1,0 0)))", srid=4326)
                )
            )

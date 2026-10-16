"""Deterministic synthetic persistence fixture, never a route calculation."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from geoalchemy2 import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
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

SEED_NAMESPACE = UUID("16a55766-b6e9-47c3-b7f3-30c1b89cf601")
SEED_TIME = datetime(2026, 10, 6, 12, tzinfo=UTC)
POINTS = {
    "A": (72.877, 19.076),
    "B": (72.878, 19.076),
    "C": (72.877, 19.075),
    "D": (72.878, 19.075),
}
EDGE_PAIRS = [
    ("A", "B"),
    ("B", "A"),
    ("A", "C"),
    ("C", "A"),
    ("B", "D"),
    ("D", "B"),
    ("C", "D"),
    ("D", "C"),
]


def seed_id(name: str) -> UUID:
    return uuid5(SEED_NAMESPACE, name)


def point(name: str) -> WKTElement:
    x, y = POINTS[name]
    return WKTElement(f"POINT({x} {y})", srid=4326)


def line(source: str, target: str) -> WKTElement:
    a, b = POINTS[source], POINTS[target]
    return WKTElement(f"LINESTRING({a[0]} {a[1]}, {b[0]} {b[1]})", srid=4326)


async def seed(session: AsyncSession) -> dict[str, int]:
    """Insert absent fixtures only; caller owns one encompassing transaction."""
    await session.execute(text("SELECT pg_advisory_xact_lock(6020202602)"))
    inserted: dict[str, int] = {}

    async def add(model, fixture_name: str, **values):
        result = await session.execute(
            insert(model)
            .values(id=seed_id(fixture_name), **values)
            .on_conflict_do_nothing(index_elements=[model.id])
            .returning(model.id)
        )
        inserted.setdefault(model.__tablename__, 0)
        inserted[model.__tablename__] += int(result.scalar_one_or_none() is not None)

    polygon = WKTElement(
        "MULTIPOLYGON(((72.8765 19.0745,72.8785 19.0745,72.8785 19.0765,"
        "72.8765 19.0765,72.8765 19.0745)))",
        srid=4326,
    )
    await add(
        User,
        "user",
        email="seed.operator@example.test",
        display_name="Synthetic operator",
        role="OPERATOR",
        created_at=SEED_TIME,
        updated_at=SEED_TIME,
    )
    await add(
        Region,
        "region",
        slug="synthetic-square",
        name="Synthetic square",
        geometry=polygon,
        created_at=SEED_TIME,
    )
    await add(
        GraphVersion,
        "graph",
        region_id=seed_id("region"),
        version=1,
        source="SYNTHETIC",
        attributes={"fixture": "phase-2-v1", "license": "synthetic"},
        created_at=SEED_TIME,
    )
    for name in POINTS:
        await add(
            RoadNode,
            f"node-{name}",
            graph_version_id=seed_id("graph"),
            location=point(name),
            elevation_m=5,
            attributes={"label": name},
            created_at=SEED_TIME,
        )
    for source, target in EDGE_PAIRS:
        geom = line(source, target)
        # PostGIS computes spheroidal meters; Python performs no coordinate-distance math.
        distance = (
            await session.execute(
                select(func.ST_Length(func.ST_GeogFromText(f"SRID=4326;{geom.desc}")))
            )
        ).scalar_one()
        await add(
            RoadEdge,
            f"edge-{source}{target}",
            graph_version_id=seed_id("graph"),
            source_node_id=seed_id(f"node-{source}"),
            target_node_id=seed_id(f"node-{target}"),
            geometry=geom,
            distance_m=distance,
            base_travel_time_s=distance / (30 / 3.6),
            road_class="residential",
            speed_limit_kph=30,
            is_one_way=False,
            attributes={"fixture": "phase-2-v1"},
            created_at=SEED_TIME,
        )
    flood_geom = WKTElement(
        "MULTIPOLYGON(((72.8774 19.0758,72.8776 19.0758,72.8776 19.0762,"
        "72.8774 19.0762,72.8774 19.0758)))",
        srid=4326,
    )
    await add(
        FloodZone,
        "zone",
        name="Synthetic extent",
        geometry=flood_geom,
        severity="HIGH",
        risk_score=0.7,
        source_type="SYNTHETIC",
        valid_from=SEED_TIME,
        valid_until=SEED_TIME + timedelta(hours=2),
        confidence=0.9,
        created_at=SEED_TIME,
        updated_at=SEED_TIME,
    )
    await add(
        SensorEvent,
        "sensor",
        producer="phase-2-seed",
        external_event_id="water-A-v1",
        sensor_id="synthetic-water-A",
        event_type="WATER_DEPTH",
        location=point("A"),
        water_depth_cm=12,
        value=12,
        unit="cm",
        quality="SIMULATED",
        observed_at=SEED_TIME,
        received_at=SEED_TIME,
    )
    await add(
        WeatherObservation,
        "weather",
        provider="phase-2-seed",
        external_id="weather-A-v1",
        location_key="synthetic-A",
        location=point("A"),
        rainfall_mm=8,
        observation_interval_minutes=60,
        temperature_c=28,
        humidity_percent=85,
        wind_speed_mps=2,
        observed_at=SEED_TIME,
        received_at=SEED_TIME,
        raw_data={"synthetic": True},
    )
    await add(
        FloodPrediction,
        "prediction",
        geometry=point("A"),
        road_edge_id=seed_id("edge-AB"),
        probability=0.7,
        predicted_water_depth_cm=18,
        risk_level="HIGH",
        model_name="synthetic-fixture",
        model_version="fixture-v1",
        feature_version="fixture-v1",
        prediction_horizon_minutes=30,
        predicted_for=SEED_TIME + timedelta(minutes=30),
        expires_at=SEED_TIME + timedelta(hours=1),
        created_at=SEED_TIME,
    )
    await add(
        Incident,
        "incident",
        reporter_user_id=seed_id("user"),
        incident_type="WATERLOGGING",
        location=point("A"),
        description="Synthetic persistence fixture",
        severity="MODERATE",
        status="REPORTED",
        confidence=0.5,
        occurred_at=SEED_TIME,
        reported_at=SEED_TIME,
        created_at=SEED_TIME,
        updated_at=SEED_TIME,
    )
    edges = list(
        (
            await session.scalars(
                select(RoadEdge).where(RoadEdge.id.in_([seed_id("edge-AB"), seed_id("edge-BD")]))
            )
        ).all()
    )
    route_geom = WKTElement("LINESTRING(72.877 19.076,72.878 19.076,72.878 19.075)", srid=4326)
    await add(
        Route,
        "route",
        user_id=seed_id("user"),
        graph_version_id=seed_id("graph"),
        source_location=point("A"),
        destination_location=point("D"),
        mode="BALANCED",
        algorithm="ASTAR",
        total_distance_m=sum(e.distance_m for e in edges),
        estimated_time_s=sum(e.base_travel_time_s for e in edges),
        risk_score=0.4,
        geometry=route_geom,
        risk_version="synthetic-risk-v1",
        policy_version="synthetic-policy-v1",
        calculated_at=SEED_TIME,
        expires_at=SEED_TIME + timedelta(hours=1),
        attributes={"synthetic": True, "calculated_by_engine": False},
    )
    edge_lookup = {e.id: e for e in edges}
    for sequence, edge_name in enumerate(["AB", "BD"]):
        edge = edge_lookup[seed_id(f"edge-{edge_name}")]
        await add(
            RouteSegment,
            f"segment-{sequence}",
            route_id=seed_id("route"),
            road_edge_id=edge.id,
            graph_version_id=seed_id("graph"),
            sequence=sequence,
            distance_m=edge.distance_m,
            travel_time_s=edge.base_travel_time_s,
            risk_score=0.4,
        )
    return inserted


async def main():
    settings = Settings()
    if settings.app_env not in {"development", "test"}:
        raise RuntimeError("Synthetic seed is restricted to development/test environments")
    database = Database(settings)
    try:
        async with database.sessions() as session, session.begin():
            inserted = await seed(session)
        print(json.dumps({"inserted": inserted}, sort_keys=True))
    finally:
        await database.close()


if __name__ == "__main__":
    asyncio.run(main())

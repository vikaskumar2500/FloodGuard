from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import (
    Base,
    CreatedAt,
    Timestamps,
    UUIDPrimaryKey,
    fraction,
    nonnegative,
    spatial_bounds,
)


class FloodZone(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "flood_zones"
    __table_args__ = (
        fraction("risk_score"),
        fraction("confidence"),
        CheckConstraint(
            "severity IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE')", name="severity_values"
        ),
        CheckConstraint("valid_until IS NULL OR valid_until > valid_from", name="validity_order"),
        spatial_bounds("geometry"),
        Index("ix_flood_zones_geometry", "geometry", postgresql_using="gist"),
        Index("ix_flood_zones_validity", "valid_from", "valid_until"),
    )
    name: Mapped[str] = mapped_column(String(160))
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False)
    )
    severity: Mapped[str] = mapped_column(String(16))
    risk_score: Mapped[float] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String(40))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class SensorEvent(UUIDPrimaryKey, Base):
    __tablename__ = "sensor_events"
    __table_args__ = (
        UniqueConstraint("producer", "external_event_id"),
        CheckConstraint(
            "btrim(producer) <> '' AND btrim(external_event_id) <> '' AND btrim(sensor_id) <> ''",
            name="identity_nonempty",
        ),
        nonnegative("rainfall_mm"),
        nonnegative("water_depth_cm"),
        CheckConstraint(
            "value > '-Infinity'::float8 AND value < 'Infinity'::float8", name="value_finite"
        ),
        CheckConstraint(
            "quality IN ('GOOD', 'SUSPECT', 'INVALID', 'SIMULATED')", name="quality_values"
        ),
        spatial_bounds("location"),
        Index("ix_sensor_events_location", "location", postgresql_using="gist"),
        Index("ix_sensor_events_sensor_observed", "sensor_id", text("observed_at DESC")),
        Index("ix_sensor_events_observed_at", "observed_at"),
    )
    producer: Mapped[str] = mapped_column(String(120))
    external_event_id: Mapped[str] = mapped_column(String(200))
    sensor_id: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(40))
    location: Mapped[WKBElement] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    rainfall_mm: Mapped[float | None] = mapped_column(Float)
    water_depth_cm: Mapped[float | None] = mapped_column(Float)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(24))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    quality: Mapped[str] = mapped_column(String(16), server_default="GOOD")
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class WeatherObservation(UUIDPrimaryKey, Base):
    __tablename__ = "weather_observations"
    __table_args__ = (
        UniqueConstraint("provider", "external_id"),
        CheckConstraint(
            "btrim(provider) <> '' AND btrim(external_id) <> '' AND btrim(location_key) <> ''",
            name="identity_nonempty",
        ),
        nonnegative("rainfall_mm"),
        nonnegative("wind_speed_mps"),
        CheckConstraint(
            "temperature_c > '-Infinity'::float8 AND temperature_c < 'Infinity'::float8",
            name="temperature_finite",
        ),
        CheckConstraint("humidity_percent BETWEEN 0 AND 100", name="humidity_range"),
        CheckConstraint("observation_interval_minutes > 0", name="interval_positive"),
        spatial_bounds("location"),
        Index("ix_weather_observations_location", "location", postgresql_using="gist"),
        Index("ix_weather_observations_observed_at", "observed_at"),
        Index(
            "ix_weather_observations_provider_location_observed",
            "provider",
            "location_key",
            text("observed_at DESC"),
        ),
    )
    provider: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(200))
    location_key: Mapped[str] = mapped_column(String(120))
    location: Mapped[WKBElement] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    rainfall_mm: Mapped[float | None] = mapped_column(Float)
    observation_interval_minutes: Mapped[int | None] = mapped_column(Integer)
    temperature_c: Mapped[float | None] = mapped_column(Float)
    humidity_percent: Mapped[float | None] = mapped_column(Float)
    wind_speed_mps: Mapped[float | None] = mapped_column(Float)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    raw_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class FloodPrediction(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "flood_predictions"
    __table_args__ = (
        fraction("probability"),
        nonnegative("predicted_water_depth_cm"),
        CheckConstraint("geometry IS NOT NULL OR road_edge_id IS NOT NULL", name="target_required"),
        CheckConstraint(
            "GeometryType(geometry) IN ('POINT', 'MULTIPOLYGON')", name="geometry_type"
        ),
        CheckConstraint(
            "risk_level IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE')", name="risk_level_values"
        ),
        CheckConstraint("prediction_horizon_minutes > 0", name="horizon_positive"),
        CheckConstraint(
            "btrim(model_name) <> '' AND btrim(model_version) <> '' "
            "AND btrim(feature_version) <> ''",
            name="lineage_nonempty",
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > predicted_for", name="expiry_order"),
        spatial_bounds("geometry"),
        Index("ix_flood_predictions_geometry", "geometry", postgresql_using="gist"),
        Index("ix_flood_predictions_predicted_for", "predicted_for"),
        Index("ix_flood_predictions_edge_predicted", "road_edge_id", "predicted_for"),
    )
    geometry: Mapped[WKBElement | None] = mapped_column(
        Geometry("GEOMETRY", srid=4326, spatial_index=False)
    )
    road_edge_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("road_edges.id", ondelete="RESTRICT")
    )
    probability: Mapped[float] = mapped_column(Float)
    predicted_water_depth_cm: Mapped[float | None] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16))
    model_name: Mapped[str] = mapped_column(String(100))
    model_version: Mapped[str] = mapped_column(String(80))
    feature_version: Mapped[str] = mapped_column(String(80))
    prediction_horizon_minutes: Mapped[int] = mapped_column(Integer)
    predicted_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

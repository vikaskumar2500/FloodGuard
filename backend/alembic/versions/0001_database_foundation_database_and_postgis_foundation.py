"""Database and PostGIS foundation

Revision ID: 0001_database_foundation
Revises:
"""

import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0001_database_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reviewed autogeneration: explicit spatial indexes, no extension-owned objects.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "flood_zones",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE')",
            name=op.f("ck_flood_zones_severity_values"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry) AND "
            "ST_XMin(Box3D(geometry)) >= -180 AND ST_XMax(Box3D(geometry)) <= 180 "
            "AND ST_YMin(Box3D(geometry)) >= -90 AND ST_YMax(Box3D(geometry)) <= 90",
            name=op.f("ck_flood_zones_geometry_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_flood_zones_confidence_range")
        ),
        sa.CheckConstraint(
            "risk_score BETWEEN 0 AND 1", name=op.f("ck_flood_zones_risk_score_range")
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name=op.f("ck_flood_zones_validity_order"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flood_zones")),
    )
    op.create_index(
        "ix_flood_zones_geometry",
        "flood_zones",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "ix_flood_zones_validity", "flood_zones", ["valid_from", "valid_until"], unique=False
    )
    op.create_table(
        "regions",
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry) AND "
            "ST_XMin(Box3D(geometry)) >= -180 AND ST_XMax(Box3D(geometry)) <= 180 "
            "AND ST_YMin(Box3D(geometry)) >= -90 AND ST_YMax(Box3D(geometry)) <= 90",
            name=op.f("ck_regions_geometry_valid_wgs84"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regions")),
        sa.UniqueConstraint("slug", name=op.f("uq_regions_slug")),
    )
    op.create_index(
        "ix_regions_geometry", "regions", ["geometry"], unique=False, postgresql_using="gist"
    )
    op.create_table(
        "sensor_events",
        sa.Column("producer", sa.String(length=120), nullable=False),
        sa.Column("external_event_id", sa.String(length=200), nullable=False),
        sa.Column("sensor_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column(
            "location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("rainfall_mm", sa.Float(), nullable=True),
        sa.Column("water_depth_cm", sa.Float(), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=24), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("quality", sa.String(length=16), server_default="GOOD", nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "btrim(producer) <> '' AND btrim(external_event_id) <> '' AND btrim(sensor_id) <> ''",
            name=op.f("ck_sensor_events_identity_nonempty"),
        ),
        sa.CheckConstraint(
            "quality IN ('GOOD', 'SUSPECT', 'INVALID', 'SIMULATED')",
            name=op.f("ck_sensor_events_quality_values"),
        ),
        sa.CheckConstraint(
            "rainfall_mm >= 0 AND rainfall_mm < 'Infinity'::float8",
            name=op.f("ck_sensor_events_rainfall_mm_nonnegative"),
        ),
        sa.CheckConstraint(
            "value > '-Infinity'::float8 AND value < 'Infinity'::float8",
            name=op.f("ck_sensor_events_value_finite"),
        ),
        sa.CheckConstraint(
            "water_depth_cm >= 0 AND water_depth_cm < 'Infinity'::float8",
            name=op.f("ck_sensor_events_water_depth_cm_nonnegative"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(location) AND ST_IsValid(location) AND "
            "ST_XMin(Box3D(location)) >= -180 AND ST_XMax(Box3D(location)) <= 180 "
            "AND ST_YMin(Box3D(location)) >= -90 AND ST_YMax(Box3D(location)) <= 90",
            name=op.f("ck_sensor_events_location_valid_wgs84"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sensor_events")),
        sa.UniqueConstraint(
            "producer", "external_event_id", name=op.f("uq_sensor_events_producer")
        ),
    )
    op.create_index(
        "ix_sensor_events_location",
        "sensor_events",
        ["location"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index("ix_sensor_events_observed_at", "sensor_events", ["observed_at"], unique=False)
    op.create_index(
        "ix_sensor_events_sensor_observed",
        "sensor_events",
        ["sensor_id", sa.literal_column("observed_at DESC")],
        unique=False,
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="USER", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email = lower(btrim(email)) AND email <> '' AND position('@' in email) > 1",
            name=op.f("ck_users_email_normalized"),
        ),
        sa.CheckConstraint(
            "role IN ('USER', 'OPERATOR', 'ADMIN')", name=op.f("ck_users_role_values")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "weather_observations",
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("external_id", sa.String(length=200), nullable=False),
        sa.Column("location_key", sa.String(length=120), nullable=False),
        sa.Column(
            "location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("rainfall_mm", sa.Float(), nullable=True),
        sa.Column("observation_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("humidity_percent", sa.Float(), nullable=True),
        sa.Column("wind_speed_mps", sa.Float(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "raw_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "btrim(provider) <> '' AND btrim(external_id) <> '' AND btrim(location_key) <> ''",
            name=op.f("ck_weather_observations_identity_nonempty"),
        ),
        sa.CheckConstraint(
            "rainfall_mm >= 0 AND rainfall_mm < 'Infinity'::float8",
            name=op.f("ck_weather_observations_rainfall_mm_nonnegative"),
        ),
        sa.CheckConstraint(
            "temperature_c > '-Infinity'::float8 AND temperature_c < 'Infinity'::float8",
            name=op.f("ck_weather_observations_temperature_finite"),
        ),
        sa.CheckConstraint(
            "wind_speed_mps >= 0 AND wind_speed_mps < 'Infinity'::float8",
            name=op.f("ck_weather_observations_wind_speed_mps_nonnegative"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(location) AND ST_IsValid(location) AND "
            "ST_XMin(Box3D(location)) >= -180 AND ST_XMax(Box3D(location)) <= 180 "
            "AND ST_YMin(Box3D(location)) >= -90 AND ST_YMax(Box3D(location)) <= 90",
            name=op.f("ck_weather_observations_location_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "humidity_percent BETWEEN 0 AND 100",
            name=op.f("ck_weather_observations_humidity_range"),
        ),
        sa.CheckConstraint(
            "observation_interval_minutes > 0",
            name=op.f("ck_weather_observations_interval_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_weather_observations")),
        sa.UniqueConstraint(
            "provider", "external_id", name=op.f("uq_weather_observations_provider")
        ),
    )
    op.create_index(
        "ix_weather_observations_location",
        "weather_observations",
        ["location"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "ix_weather_observations_observed_at", "weather_observations", ["observed_at"], unique=False
    )
    op.create_index(
        "ix_weather_observations_provider_location_observed",
        "weather_observations",
        ["provider", "location_key", sa.literal_column("observed_at DESC")],
        unique=False,
    )
    op.create_table(
        "graph_versions",
        sa.Column("region_id", sa.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name=op.f("ck_graph_versions_version_positive")),
        sa.ForeignKeyConstraint(
            ["region_id"],
            ["regions.id"],
            name=op.f("fk_graph_versions_region_id_regions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_versions")),
        sa.UniqueConstraint("region_id", "version", name=op.f("uq_graph_versions_region_id")),
    )
    op.create_table(
        "incidents",
        sa.Column("reporter_user_id", sa.UUID(), nullable=True),
        sa.Column("incident_type", sa.String(length=24), nullable=False),
        sa.Column(
            "location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="REPORTED", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "reported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "incident_type IN ('WATERLOGGING', 'ROAD_BLOCKED', 'HIGH_WATER', "
            "'FALLEN_TREE', 'ROAD_DAMAGE', 'OTHER')",
            name=op.f("ck_incidents_type_values"),
        ),
        sa.CheckConstraint(
            "severity IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE')",
            name=op.f("ck_incidents_severity_values"),
        ),
        sa.CheckConstraint(
            "status IN ('REPORTED', 'VERIFIED', 'RESOLVED', 'REJECTED')",
            name=op.f("ck_incidents_status_values"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(location) AND ST_IsValid(location) AND "
            "ST_XMin(Box3D(location)) >= -180 AND ST_XMax(Box3D(location)) <= 180 "
            "AND ST_YMin(Box3D(location)) >= -90 AND ST_YMax(Box3D(location)) <= 90",
            name=op.f("ck_incidents_location_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1", name=op.f("ck_incidents_confidence_range")
        ),
        sa.CheckConstraint(
            "verified_at IS NULL OR verified_at >= reported_at",
            name=op.f("ck_incidents_verification_order"),
        ),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"],
            ["users.id"],
            name=op.f("fk_incidents_reporter_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(
        "ix_incidents_location", "incidents", ["location"], unique=False, postgresql_using="gist"
    )
    op.create_index("ix_incidents_reporter", "incidents", ["reporter_user_id"], unique=False)
    op.create_index(
        "ix_incidents_status_occurred", "incidents", ["status", "occurred_at"], unique=False
    )
    op.create_table(
        "road_nodes",
        sa.Column("graph_version_id", sa.UUID(), nullable=False),
        sa.Column("osm_node_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "elevation_m > '-Infinity'::float8 AND elevation_m < 'Infinity'::float8",
            name=op.f("ck_road_nodes_elevation_finite"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(location) AND ST_IsValid(location) AND "
            "ST_XMin(Box3D(location)) >= -180 AND ST_XMax(Box3D(location)) <= 180 "
            "AND ST_YMin(Box3D(location)) >= -90 AND ST_YMax(Box3D(location)) <= 90",
            name=op.f("ck_road_nodes_location_valid_wgs84"),
        ),
        sa.CheckConstraint("osm_node_id > 0", name=op.f("ck_road_nodes_osm_node_id_positive")),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["graph_versions.id"],
            name=op.f("fk_road_nodes_graph_version_id_graph_versions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_road_nodes")),
        sa.UniqueConstraint(
            "graph_version_id", "osm_node_id", name=op.f("uq_road_nodes_graph_version_id")
        ),
        sa.UniqueConstraint("id", "graph_version_id", name=op.f("uq_road_nodes_id")),
    )
    op.create_index(
        "ix_road_nodes_location", "road_nodes", ["location"], unique=False, postgresql_using="gist"
    )
    op.create_index(
        "ix_road_nodes_location_geography",
        "road_nodes",
        [sa.literal_column("(location::geography)")],
        unique=False,
        postgresql_using="gist",
    )
    op.create_table(
        "routes",
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("graph_version_id", sa.UUID(), nullable=False),
        sa.Column(
            "source_location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "destination_location",
            Geometry(geometry_type="POINT", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("algorithm", sa.String(length=16), nullable=False),
        sa.Column("total_distance_m", sa.Float(), nullable=False),
        sa.Column("estimated_time_s", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("risk_version", sa.String(length=80), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "algorithm IN ('DIJKSTRA', 'ASTAR')", name=op.f("ck_routes_algorithm_values")
        ),
        sa.CheckConstraint(
            "btrim(risk_version) <> '' AND btrim(policy_version) <> ''",
            name=op.f("ck_routes_versions_nonempty"),
        ),
        sa.CheckConstraint(
            "estimated_time_s >= 0 AND estimated_time_s < 'Infinity'::float8",
            name=op.f("ck_routes_estimated_time_s_nonnegative"),
        ),
        sa.CheckConstraint(
            "mode IN ('FASTEST', 'BALANCED', 'SAFEST')", name=op.f("ck_routes_mode_values")
        ),
        sa.CheckConstraint(
            "total_distance_m >= 0 AND total_distance_m < 'Infinity'::float8",
            name=op.f("ck_routes_total_distance_m_nonnegative"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(destination_location) AND "
            "ST_IsValid(destination_location) AND "
            "ST_XMin(Box3D(destination_location)) >= -180 AND "
            "ST_XMax(Box3D(destination_location)) <= 180 AND "
            "ST_YMin(Box3D(destination_location)) >= -90 AND "
            "ST_YMax(Box3D(destination_location)) <= 90",
            name=op.f("ck_routes_destination_location_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry) AND "
            "ST_XMin(Box3D(geometry)) >= -180 AND ST_XMax(Box3D(geometry)) <= 180 "
            "AND ST_YMin(Box3D(geometry)) >= -90 AND ST_YMax(Box3D(geometry)) <= 90",
            name=op.f("ck_routes_geometry_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(source_location) AND ST_IsValid(source_location) AND "
            "ST_XMin(Box3D(source_location)) >= -180 AND "
            "ST_XMax(Box3D(source_location)) <= 180 AND "
            "ST_YMin(Box3D(source_location)) >= -90 AND "
            "ST_YMax(Box3D(source_location)) <= 90",
            name=op.f("ck_routes_source_location_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > calculated_at", name=op.f("ck_routes_expiry_order")
        ),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 1", name=op.f("ck_routes_risk_score_range")),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["graph_versions.id"],
            name=op.f("fk_routes_graph_version_id_graph_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_routes_user_id_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routes")),
        sa.UniqueConstraint("id", "graph_version_id", name=op.f("uq_routes_id")),
    )
    op.create_index("ix_routes_expires_at", "routes", ["expires_at"], unique=False)
    op.create_index(
        "ix_routes_geometry", "routes", ["geometry"], unique=False, postgresql_using="gist"
    )
    op.create_index("ix_routes_graph_version_id", "routes", ["graph_version_id"], unique=False)
    op.create_index(
        "ix_routes_user_calculated",
        "routes",
        ["user_id", sa.literal_column("calculated_at DESC")],
        unique=False,
    )
    op.create_table(
        "road_edges",
        sa.Column("graph_version_id", sa.UUID(), nullable=False),
        sa.Column("osm_way_id", sa.BigInteger(), nullable=True),
        sa.Column("osm_segment_index", sa.Integer(), nullable=True),
        sa.Column("osm_direction", sa.SmallInteger(), nullable=True),
        sa.Column("source_node_id", sa.Uuid(), nullable=False),
        sa.Column("target_node_id", sa.Uuid(), nullable=False),
        sa.Column(
            "geometry",
            Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("base_travel_time_s", sa.Float(), nullable=False),
        sa.Column("road_class", sa.String(length=40), nullable=False),
        sa.Column("speed_limit_kph", sa.Float(), nullable=True),
        sa.Column("is_one_way", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "base_travel_time_s >= 0 AND base_travel_time_s < 'Infinity'::float8",
            name=op.f("ck_road_edges_base_travel_time_s_nonnegative"),
        ),
        sa.CheckConstraint(
            "distance_m >= 0 AND distance_m < 'Infinity'::float8",
            name=op.f("ck_road_edges_distance_m_nonnegative"),
        ),
        sa.CheckConstraint(
            "speed_limit_kph > 0 AND speed_limit_kph < 'Infinity'::float8",
            name=op.f("ck_road_edges_speed_positive"),
        ),
        sa.CheckConstraint(
            "(osm_way_id IS NULL AND osm_segment_index IS NULL AND osm_direction IS"
            " NULL) OR (osm_way_id IS NOT NULL AND osm_way_id > 0 AND "
            "osm_segment_index IS NOT NULL AND osm_segment_index >= 0 AND "
            "osm_direction IS NOT NULL AND osm_direction IN (-1, 1))",
            name=op.f("ck_road_edges_osm_identity_complete"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry) AND "
            "ST_XMin(Box3D(geometry)) >= -180 AND ST_XMax(Box3D(geometry)) <= 180 "
            "AND ST_YMin(Box3D(geometry)) >= -90 AND ST_YMax(Box3D(geometry)) <= 90",
            name=op.f("ck_road_edges_geometry_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "source_node_id <> target_node_id", name=op.f("ck_road_edges_distinct_nodes")
        ),
        sa.ForeignKeyConstraint(
            ["graph_version_id"],
            ["graph_versions.id"],
            name=op.f("fk_road_edges_graph_version_id_graph_versions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_node_id", "graph_version_id"],
            ["road_nodes.id", "road_nodes.graph_version_id"],
            name="fk_road_edges_source_graph",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id", "graph_version_id"],
            ["road_nodes.id", "road_nodes.graph_version_id"],
            name="fk_road_edges_target_graph",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_road_edges")),
        sa.UniqueConstraint(
            "graph_version_id",
            "osm_way_id",
            "osm_segment_index",
            "osm_direction",
            name=op.f("uq_road_edges_graph_version_id"),
        ),
        sa.UniqueConstraint("id", "graph_version_id", name=op.f("uq_road_edges_id")),
    )
    op.create_index(
        "ix_road_edges_geometry", "road_edges", ["geometry"], unique=False, postgresql_using="gist"
    )
    op.create_index(
        "ix_road_edges_graph_source",
        "road_edges",
        ["graph_version_id", "source_node_id"],
        unique=False,
    )
    op.create_index(
        "ix_road_edges_graph_target",
        "road_edges",
        ["graph_version_id", "target_node_id"],
        unique=False,
    )
    op.create_table(
        "flood_predictions",
        sa.Column(
            "geometry",
            Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False),
            nullable=True,
        ),
        sa.Column("road_edge_id", sa.UUID(), nullable=True),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("predicted_water_depth_cm", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(length=16), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column("feature_version", sa.String(length=80), nullable=False),
        sa.Column("prediction_horizon_minutes", sa.Integer(), nullable=False),
        sa.Column("predicted_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "GeometryType(geometry) IN ('POINT', 'MULTIPOLYGON')",
            name=op.f("ck_flood_predictions_geometry_type"),
        ),
        sa.CheckConstraint(
            "btrim(model_name) <> '' AND btrim(model_version) <> '' AND "
            "btrim(feature_version) <> ''",
            name=op.f("ck_flood_predictions_lineage_nonempty"),
        ),
        sa.CheckConstraint(
            "predicted_water_depth_cm >= 0 AND predicted_water_depth_cm < 'Infinity'::float8",
            name=op.f("ck_flood_predictions_predicted_water_depth_cm_nonnegative"),
        ),
        sa.CheckConstraint(
            "risk_level IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE')",
            name=op.f("ck_flood_predictions_risk_level_values"),
        ),
        sa.CheckConstraint(
            "NOT ST_IsEmpty(geometry) AND ST_IsValid(geometry) AND "
            "ST_XMin(Box3D(geometry)) >= -180 AND ST_XMax(Box3D(geometry)) <= 180 "
            "AND ST_YMin(Box3D(geometry)) >= -90 AND ST_YMax(Box3D(geometry)) <= 90",
            name=op.f("ck_flood_predictions_geometry_valid_wgs84"),
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > predicted_for",
            name=op.f("ck_flood_predictions_expiry_order"),
        ),
        sa.CheckConstraint(
            "geometry IS NOT NULL OR road_edge_id IS NOT NULL",
            name=op.f("ck_flood_predictions_target_required"),
        ),
        sa.CheckConstraint(
            "prediction_horizon_minutes > 0", name=op.f("ck_flood_predictions_horizon_positive")
        ),
        sa.CheckConstraint(
            "probability BETWEEN 0 AND 1", name=op.f("ck_flood_predictions_probability_range")
        ),
        sa.ForeignKeyConstraint(
            ["road_edge_id"],
            ["road_edges.id"],
            name=op.f("fk_flood_predictions_road_edge_id_road_edges"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_flood_predictions")),
    )
    op.create_index(
        "ix_flood_predictions_edge_predicted",
        "flood_predictions",
        ["road_edge_id", "predicted_for"],
        unique=False,
    )
    op.create_index(
        "ix_flood_predictions_geometry",
        "flood_predictions",
        ["geometry"],
        unique=False,
        postgresql_using="gist",
    )
    op.create_index(
        "ix_flood_predictions_predicted_for", "flood_predictions", ["predicted_for"], unique=False
    )
    op.create_table(
        "route_segments",
        sa.Column("route_id", sa.Uuid(), nullable=False),
        sa.Column("road_edge_id", sa.Uuid(), nullable=False),
        sa.Column("graph_version_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("travel_time_s", sa.Float(), nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.CheckConstraint(
            "distance_m >= 0 AND distance_m < 'Infinity'::float8",
            name=op.f("ck_route_segments_distance_m_nonnegative"),
        ),
        sa.CheckConstraint(
            "travel_time_s >= 0 AND travel_time_s < 'Infinity'::float8",
            name=op.f("ck_route_segments_travel_time_s_nonnegative"),
        ),
        sa.CheckConstraint(
            "risk_score BETWEEN 0 AND 1", name=op.f("ck_route_segments_risk_score_range")
        ),
        sa.CheckConstraint("sequence >= 0", name=op.f("ck_route_segments_sequence_nonnegative")),
        sa.ForeignKeyConstraint(
            ["road_edge_id", "graph_version_id"],
            ["road_edges.id", "road_edges.graph_version_id"],
            name="fk_route_segments_edge_graph",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["route_id", "graph_version_id"],
            ["routes.id", "routes.graph_version_id"],
            name="fk_route_segments_route_graph",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_route_segments")),
        sa.UniqueConstraint("route_id", "sequence", name=op.f("uq_route_segments_route_id")),
    )
    op.create_index(
        "ix_route_segments_edge_route", "route_segments", ["road_edge_id", "route_id"], unique=False
    )
    op.execute("""
        CREATE FUNCTION floodguard_set_updated_at() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = clock_timestamp();
            RETURN NEW;
        END;
        $$
    """)
    for table in ("users", "flood_zones", "incidents"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION floodguard_set_updated_at()"
        )


def downgrade() -> None:
    for table in ("users", "flood_zones", "incidents"):
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION floodguard_set_updated_at()")
    op.drop_index("ix_route_segments_edge_route", table_name="route_segments")
    op.drop_table("route_segments")
    op.drop_index("ix_flood_predictions_predicted_for", table_name="flood_predictions")
    op.drop_index(
        "ix_flood_predictions_geometry", table_name="flood_predictions", postgresql_using="gist"
    )
    op.drop_index("ix_flood_predictions_edge_predicted", table_name="flood_predictions")
    op.drop_table("flood_predictions")
    op.drop_index("ix_road_edges_graph_target", table_name="road_edges")
    op.drop_index("ix_road_edges_graph_source", table_name="road_edges")
    op.drop_index("ix_road_edges_geometry", table_name="road_edges", postgresql_using="gist")
    op.drop_table("road_edges")
    op.drop_index("ix_routes_user_calculated", table_name="routes")
    op.drop_index("ix_routes_graph_version_id", table_name="routes")
    op.drop_index("ix_routes_geometry", table_name="routes", postgresql_using="gist")
    op.drop_index("ix_routes_expires_at", table_name="routes")
    op.drop_table("routes")
    op.drop_index(
        "ix_road_nodes_location_geography", table_name="road_nodes", postgresql_using="gist"
    )
    op.drop_index("ix_road_nodes_location", table_name="road_nodes", postgresql_using="gist")
    op.drop_table("road_nodes")
    op.drop_index("ix_incidents_status_occurred", table_name="incidents")
    op.drop_index("ix_incidents_reporter", table_name="incidents")
    op.drop_index("ix_incidents_location", table_name="incidents", postgresql_using="gist")
    op.drop_table("incidents")
    op.drop_table("graph_versions")
    op.drop_index(
        "ix_weather_observations_provider_location_observed", table_name="weather_observations"
    )
    op.drop_index("ix_weather_observations_observed_at", table_name="weather_observations")
    op.drop_index(
        "ix_weather_observations_location",
        table_name="weather_observations",
        postgresql_using="gist",
    )
    op.drop_table("weather_observations")
    op.drop_table("users")
    op.drop_index("ix_sensor_events_sensor_observed", table_name="sensor_events")
    op.drop_index("ix_sensor_events_observed_at", table_name="sensor_events")
    op.drop_index("ix_sensor_events_location", table_name="sensor_events", postgresql_using="gist")
    op.drop_table("sensor_events")
    op.drop_index("ix_regions_geometry", table_name="regions", postgresql_using="gist")
    op.drop_table("regions")
    op.drop_index("ix_flood_zones_validity", table_name="flood_zones")
    op.drop_index("ix_flood_zones_geometry", table_name="flood_zones", postgresql_using="gist")
    op.drop_table("flood_zones")
    # Retain shared PostGIS: it may predate this revision or serve unrelated schemas.

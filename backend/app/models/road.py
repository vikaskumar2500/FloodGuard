from uuid import UUID

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPrimaryKey, nonnegative, spatial_bounds


class Region(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("slug"),
        spatial_bounds("geometry"),
        Index("ix_regions_geometry", "geometry", postgresql_using="gist"),
    )

    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326, spatial_index=False)
    )


class GraphVersion(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "graph_versions"
    __table_args__ = (
        UniqueConstraint("region_id", "version"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    region_id: Mapped[UUID] = mapped_column(ForeignKey("regions.id", ondelete="RESTRICT"))
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(80))
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class RoadNode(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "road_nodes"
    __table_args__ = (
        UniqueConstraint("id", "graph_version_id"),
        UniqueConstraint("graph_version_id", "osm_node_id"),
        CheckConstraint("osm_node_id > 0", name="osm_node_id_positive"),
        CheckConstraint(
            "elevation_m > '-Infinity'::float8 AND elevation_m < 'Infinity'::float8",
            name="elevation_finite",
        ),
        spatial_bounds("location"),
        Index("ix_road_nodes_location", "location", postgresql_using="gist"),
        Index(
            "ix_road_nodes_location_geography",
            text("(location::geography)"),
            postgresql_using="gist",
        ),
    )

    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="RESTRICT")
    )
    osm_node_id: Mapped[int | None] = mapped_column(BigInteger)
    location: Mapped[WKBElement] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    elevation_m: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class RoadEdge(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "road_edges"
    __table_args__ = (
        UniqueConstraint("id", "graph_version_id"),
        UniqueConstraint("graph_version_id", "osm_way_id", "osm_segment_index", "osm_direction"),
        ForeignKeyConstraint(
            ["source_node_id", "graph_version_id"],
            ["road_nodes.id", "road_nodes.graph_version_id"],
            name="fk_road_edges_source_graph",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["target_node_id", "graph_version_id"],
            ["road_nodes.id", "road_nodes.graph_version_id"],
            name="fk_road_edges_target_graph",
            ondelete="RESTRICT",
        ),
        CheckConstraint("source_node_id <> target_node_id", name="distinct_nodes"),
        CheckConstraint(
            "(osm_way_id IS NULL AND osm_segment_index IS NULL AND osm_direction IS NULL) OR "
            "(osm_way_id IS NOT NULL AND osm_way_id > 0 AND osm_segment_index IS NOT NULL "
            "AND osm_segment_index >= 0 AND osm_direction IS NOT NULL "
            "AND osm_direction IN (-1, 1))",
            name="osm_identity_complete",
        ),
        nonnegative("distance_m"),
        nonnegative("base_travel_time_s"),
        CheckConstraint(
            "speed_limit_kph > 0 AND speed_limit_kph < 'Infinity'::float8", name="speed_positive"
        ),
        spatial_bounds("geometry"),
        Index("ix_road_edges_graph_source", "graph_version_id", "source_node_id"),
        Index("ix_road_edges_graph_target", "graph_version_id", "target_node_id"),
        Index("ix_road_edges_geometry", "geometry", postgresql_using="gist"),
    )

    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="RESTRICT")
    )
    osm_way_id: Mapped[int | None] = mapped_column(BigInteger)
    osm_segment_index: Mapped[int | None] = mapped_column(Integer)
    osm_direction: Mapped[int | None] = mapped_column(SmallInteger)
    source_node_id: Mapped[UUID]
    target_node_id: Mapped[UUID]
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry("LINESTRING", srid=4326, spatial_index=False)
    )
    distance_m: Mapped[float] = mapped_column(Float)
    base_travel_time_s: Mapped[float] = mapped_column(Float)
    road_class: Mapped[str] = mapped_column(String(40))
    speed_limit_kph: Mapped[float | None] = mapped_column(Float)
    is_one_way: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKey, fraction, nonnegative, spatial_bounds


class Route(UUIDPrimaryKey, Base):
    """One immutable calculation; stable journey heads/revisions arrive in later phases."""

    __tablename__ = "routes"
    __table_args__ = (
        UniqueConstraint("id", "graph_version_id"),
        CheckConstraint("mode IN ('FASTEST', 'BALANCED', 'SAFEST')", name="mode_values"),
        CheckConstraint("algorithm IN ('DIJKSTRA', 'ASTAR')", name="algorithm_values"),
        CheckConstraint(
            "btrim(risk_version) <> '' AND btrim(policy_version) <> ''", name="versions_nonempty"
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > calculated_at", name="expiry_order"),
        nonnegative("total_distance_m"),
        nonnegative("estimated_time_s"),
        fraction("risk_score"),
        spatial_bounds("source_location"),
        spatial_bounds("destination_location"),
        spatial_bounds("geometry"),
        Index("ix_routes_geometry", "geometry", postgresql_using="gist"),
        Index("ix_routes_user_calculated", "user_id", text("calculated_at DESC")),
        Index("ix_routes_expires_at", "expires_at"),
        Index("ix_routes_graph_version_id", "graph_version_id"),
    )
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    graph_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("graph_versions.id", ondelete="RESTRICT")
    )
    source_location: Mapped[WKBElement] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False)
    )
    destination_location: Mapped[WKBElement] = mapped_column(
        Geometry("POINT", srid=4326, spatial_index=False)
    )
    mode: Mapped[str] = mapped_column(String(16))
    algorithm: Mapped[str] = mapped_column(String(16))
    total_distance_m: Mapped[float] = mapped_column(Float)
    estimated_time_s: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[WKBElement] = mapped_column(
        Geometry("LINESTRING", srid=4326, spatial_index=False)
    )
    risk_version: Mapped[str] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(80))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    segments: Mapped[list["RouteSegment"]] = relationship(
        back_populates="route",
        lazy="raise",
        passive_deletes=True,
        cascade="all, delete-orphan",
        order_by="RouteSegment.sequence",
        foreign_keys="[RouteSegment.route_id, RouteSegment.graph_version_id]",
    )


class RouteSegment(UUIDPrimaryKey, Base):
    __tablename__ = "route_segments"
    __table_args__ = (
        UniqueConstraint("route_id", "sequence"),
        ForeignKeyConstraint(
            ["route_id", "graph_version_id"],
            ["routes.id", "routes.graph_version_id"],
            name="fk_route_segments_route_graph",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["road_edge_id", "graph_version_id"],
            ["road_edges.id", "road_edges.graph_version_id"],
            name="fk_route_segments_edge_graph",
            ondelete="RESTRICT",
        ),
        CheckConstraint("sequence >= 0", name="sequence_nonnegative"),
        nonnegative("distance_m"),
        nonnegative("travel_time_s"),
        fraction("risk_score"),
        Index("ix_route_segments_edge_route", "road_edge_id", "route_id"),
    )
    route_id: Mapped[UUID] = mapped_column()
    road_edge_id: Mapped[UUID] = mapped_column()
    graph_version_id: Mapped[UUID] = mapped_column()
    sequence: Mapped[int] = mapped_column(Integer)
    distance_m: Mapped[float] = mapped_column(Float)
    travel_time_s: Mapped[float] = mapped_column(Float)
    risk_score: Mapped[float | None] = mapped_column(Float)
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    route: Mapped[Route] = relationship(
        back_populates="segments", lazy="raise", foreign_keys=[route_id, graph_version_id]
    )

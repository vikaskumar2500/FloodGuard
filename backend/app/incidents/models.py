from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geometry, WKBElement
from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPrimaryKey, fraction, spatial_bounds


class Incident(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint(
            "incident_type IN ('WATERLOGGING', 'FLOODED_ROAD', 'ROAD_BLOCKED', 'HIGH_WATER', "
            "'FALLEN_TREE', 'ROAD_DAMAGE', 'OTHER')",
            name="type_values",
        ),
        CheckConstraint(
            "severity IN ('LOW', 'MODERATE', 'HIGH', 'SEVERE')", name="severity_values"
        ),
        CheckConstraint(
            "status IN ('REPORTED', 'UNDER_REVIEW', 'VERIFIED', 'DISPUTED', 'REJECTED', 'RESOLVED', 'EXPIRED')",
            name="status_values",
        ),
        CheckConstraint(
            "verified_at IS NULL OR verified_at >= reported_at", name="verification_order"
        ),
        fraction("confidence"),
        spatial_bounds("location"),
        Index("ix_incidents_location", "location", postgresql_using="gist"),
        Index("ix_incidents_status_occurred", "status", "occurred_at"),
        Index("ix_incidents_reporter", "reporter_user_id"),
    )
    reporter_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    incident_type: Mapped[str] = mapped_column(String(24))
    location: Mapped[WKBElement] = mapped_column(Geometry("POINT", srid=4326, spatial_index=False))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="REPORTED")
    confidence: Mapped[float | None] = mapped_column(Float)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

"""PostgreSQL model conventions shared by the domain and Alembic."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKey:
    # PostgreSQL core supplies gen_random_uuid(); pgcrypto is unnecessary on PG 17.
    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4, server_default=func.gen_random_uuid()
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Timestamps(CreatedAt):
    # A migration-managed trigger also covers writes outside the ORM.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), server_onupdate=func.now()
    )


def nonnegative(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"{column} >= 0 AND {column} < 'Infinity'::float8", name=f"{column}_nonnegative"
    )


def fraction(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} BETWEEN 0 AND 1", name=f"{column}_range")


def spatial_bounds(column: str) -> CheckConstraint:
    return CheckConstraint(
        f"NOT ST_IsEmpty({column}) AND ST_IsValid({column}) "
        f"AND ST_XMin(Box3D({column})) >= -180 AND ST_XMax(Box3D({column})) <= 180 "
        f"AND ST_YMin(Box3D({column})) >= -90 AND ST_YMax(Box3D({column})) <= 90",
        name=f"{column}_valid_wgs84",
    )

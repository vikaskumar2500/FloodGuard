"""Asyncpg migrations; never run migrations as an API startup side effect."""

import asyncio
from logging.config import fileConfig

from geoalchemy2 import Geometry
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app import models  # noqa: F401
from app.core.config import Settings
from app.db.base import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)


def include_name(name, type_, parent_names):
    # PostGIS extension objects are owned by PostGIS, never by application migrations.
    if type_ == "table":
        return name in Base.metadata.tables
    return True


def render_item(type_, obj, autogen_context):
    if type_ == "type" and isinstance(obj, Geometry):
        autogen_context.imports.add("from geoalchemy2 import Geometry")
        return (
            f"Geometry(geometry_type={obj.geometry_type!r}, srid={obj.srid}, spatial_index=False)"
        )
    return False


def configure(**kwargs):
    context.configure(
        target_metadata=Base.metadata,
        include_name=include_name,
        render_item=render_item,
        compare_type=True,
        **kwargs,
    )


def run_migrations_offline():
    configure(dialect_name="postgresql", literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    engine = create_async_engine(
        Settings().database_url.get_secret_value(), poolclass=pool.NullPool
    )
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
elif (connection := config.attributes.get("connection")) is not None:
    do_run_migrations(connection)
else:
    asyncio.run(run_async_migrations())

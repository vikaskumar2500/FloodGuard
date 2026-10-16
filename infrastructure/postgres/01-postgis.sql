-- Infrastructure bootstrap; Alembic independently ensures PostGIS and owns domain DDL.
CREATE EXTENSION IF NOT EXISTS postgis;

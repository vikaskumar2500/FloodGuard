import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.core.redis import create_redis_client
from app.db.session import Database
from app.main import create_app
from app.services.health import check_database, check_redis

pytestmark = pytest.mark.integration


async def test_live_postgres_and_postgis():
    settings = Settings()
    database = Database(settings)
    try:
        result = await check_database(
            database.engine, settings.health_check_timeout_seconds, "test"
        )
        assert result["postgres"].status == "healthy"
        assert result["postgis"].status == "healthy"
        async with database.sessions() as session:
            version = (await session.execute(text("SELECT PostGIS_Version()"))).scalar_one()
            assert isinstance(version, str) and version
            assert (await session.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        await database.close()


async def test_live_redis():
    settings = Settings()
    redis = create_redis_client(settings)
    try:
        assert (
            await check_redis(redis, settings.health_check_timeout_seconds, "test")
        ).status == "healthy"
    finally:
        await redis.aclose()


def test_live_api_readiness():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 200
        assert response.json()["ready"] is True
        assert all(item["status"] == "healthy" for item in response.json()["dependencies"].values())

import asyncio
import logging

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.schemas.health import DependencyHealth, ReadinessResponse

logger = logging.getLogger("floodguard.health")


async def check_database(
    engine: AsyncEngine, timeout_seconds: float, request_id: str
) -> dict[str, DependencyHealth]:
    try:
        async with asyncio.timeout(timeout_seconds), engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            postgres = DependencyHealth(status="healthy", message="Database reachable")
            try:
                version = (await connection.execute(text("SELECT PostGIS_Version()"))).scalar_one()
                if not version:
                    raise ValueError("Missing PostGIS version")
                postgis = DependencyHealth(status="healthy", message="PostGIS extension available")
            except Exception as error:
                logger.warning(
                    "dependency_readiness_failed",
                    extra={
                        "dependency": "postgis",
                        "error_type": type(error).__name__,
                        "request_id": request_id,
                    },
                )
                postgis = DependencyHealth(status="unavailable", message="PostGIS unavailable")
            return {"postgres": postgres, "postgis": postgis}
    except Exception as error:
        logger.warning(
            "dependency_readiness_failed",
            extra={
                "dependency": "postgres",
                "error_type": type(error).__name__,
                "request_id": request_id,
            },
        )
        return {
            "postgres": DependencyHealth(status="unavailable", message="Database unavailable"),
            "postgis": DependencyHealth(status="unavailable", message="PostGIS not verified"),
        }


async def check_redis(client: Redis, timeout_seconds: float, request_id: str) -> DependencyHealth:
    try:
        async with asyncio.timeout(timeout_seconds):
            if not await client.ping():
                raise ConnectionError("Redis ping failed")
        return DependencyHealth(status="healthy", message="Redis reachable")
    except Exception as error:
        logger.warning(
            "dependency_readiness_failed",
            extra={
                "dependency": "redis",
                "error_type": type(error).__name__,
                "request_id": request_id,
            },
        )
        return DependencyHealth(status="unavailable", message="Redis unavailable")


class HealthService:
    def __init__(self, engine: AsyncEngine, redis: Redis, settings: Settings) -> None:
        self.engine = engine
        self.redis = redis
        self.settings = settings

    async def readiness(self, request_id: str) -> ReadinessResponse:
        database, redis = await asyncio.gather(
            check_database(self.engine, self.settings.health_check_timeout_seconds, request_id),
            check_redis(self.redis, self.settings.health_check_timeout_seconds, request_id),
        )
        dependencies = {**database, "redis": redis}
        database_ready = all(value.status == "healthy" for value in database.values())
        redis_ready = redis.status == "healthy"
        return ReadinessResponse(
            status=(
                "unavailable" if not database_ready else "healthy" if redis_ready else "degraded"
            ),
            ready=database_ready and (redis_ready or not self.settings.redis_required),
            service=self.settings.app_name,
            version=self.settings.app_version,
            request_id=request_id,
            dependencies=dependencies,
        )

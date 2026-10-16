import logging
from uuid import UUID

from redis.asyncio import Redis

from .keys import route_cache_key
from .metrics import CacheMetrics
from .models import CachedRouteTemplateDTO
from .serializer import deserialize_model, serialize_model

logger = logging.getLogger("floodguard.cache.route")


class RouteCache:
    """Cache-aside manager for route calculation templates.

    Stores deterministic route calculation geometries and risk assessments keyed by
    graph version, endpoints, routing mode, algorithm, and runtime risk revision.
    """

    def __init__(
        self,
        redis: Redis | None,
        ttl_seconds: int = 3600,
        enabled: bool = True,
        metrics: CacheMetrics | None = None,
    ) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self.metrics = metrics or CacheMetrics()

    async def get(
        self,
        graph_version_id: UUID | str,
        source_node_id: UUID | str,
        destination_node_id: UUID | str,
        mode: str,
        algorithm: str,
        risk_revision: int,
        config_hash: str,
    ) -> CachedRouteTemplateDTO | None:
        if not self.enabled or self.redis is None:
            self.metrics.record_bypassed("route")
            return None

        key = route_cache_key(
            graph_version_id,
            source_node_id,
            destination_node_id,
            mode,
            algorithm,
            risk_revision,
            config_hash,
        )
        try:
            raw = await self.redis.get(key)
            if raw is None:
                self.metrics.record_miss("route")
                return None

            dto = deserialize_model(raw, CachedRouteTemplateDTO)
            if dto is None:
                self.metrics.record_miss("route")
                return None

            self.metrics.record_hit("route")
            return dto
        except Exception as error:
            logger.warning(
                "route_cache_read_error",
                extra={
                    "key": key,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            self.metrics.record_error("route")
            return None

    async def set(
        self,
        graph_version_id: UUID | str,
        source_node_id: UUID | str,
        destination_node_id: UUID | str,
        mode: str,
        algorithm: str,
        risk_revision: int,
        config_hash: str,
        template: CachedRouteTemplateDTO,
    ) -> bool:
        if not self.enabled or self.redis is None:
            return False

        key = route_cache_key(
            graph_version_id,
            source_node_id,
            destination_node_id,
            mode,
            algorithm,
            risk_revision,
            config_hash,
        )
        try:
            payload = serialize_model(template)
            await self.redis.set(key, payload, ex=self.ttl_seconds)
            self.metrics.record_set("route")
            return True
        except Exception as error:
            logger.warning(
                "route_cache_write_error",
                extra={
                    "key": key,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            self.metrics.record_error("route")
            return False

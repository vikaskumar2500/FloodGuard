import logging
from uuid import UUID

from redis.asyncio import Redis

from app.routing.models import RoutingGraph

from .keys import graph_cache_key
from .metrics import CacheMetrics
from .models import CachedGraphDTO
from .serializer import deserialize_model, dto_to_graph, graph_to_dto, serialize_model

logger = logging.getLogger("floodguard.cache.graph")


class GraphCache:
    """Cache-aside manager for immutable RoutingGraph instances."""

    def __init__(
        self,
        redis: Redis | None,
        ttl_seconds: int = 86400,
        max_bytes: int = 50 * 1024 * 1024,
        enabled: bool = True,
        metrics: CacheMetrics | None = None,
    ) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.max_bytes = max_bytes
        self.enabled = enabled
        self.metrics = metrics or CacheMetrics()

    async def get(self, graph_version_id: UUID | str) -> RoutingGraph | None:
        if not self.enabled or self.redis is None:
            self.metrics.record_bypassed("graph")
            return None

        key = graph_cache_key(graph_version_id)
        try:
            raw = await self.redis.get(key)
            if raw is None:
                self.metrics.record_miss("graph")
                return None

            dto = deserialize_model(raw, CachedGraphDTO)
            if dto is None:
                self.metrics.record_miss("graph")
                return None

            graph = dto_to_graph(dto)
            self.metrics.record_hit("graph")
            return graph
        except Exception as error:
            logger.warning(
                "graph_cache_read_error",
                extra={
                    "key": key,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            self.metrics.record_error("graph")
            return None

    async def set(self, graph_version_id: UUID | str, graph: RoutingGraph) -> bool:
        if not self.enabled or self.redis is None:
            return False

        key = graph_cache_key(graph_version_id)
        try:
            dto = graph_to_dto(graph_version_id, graph)
            payload = serialize_model(dto)
            size_bytes = len(payload.encode("utf-8"))
            if size_bytes > self.max_bytes:
                logger.warning(
                    "graph_cache_payload_too_large",
                    extra={"key": key, "size_bytes": size_bytes, "max_bytes": self.max_bytes},
                )
                return False

            await self.redis.set(key, payload, ex=self.ttl_seconds)
            self.metrics.record_set("graph")
            return True
        except Exception as error:
            logger.warning(
                "graph_cache_write_error",
                extra={
                    "key": key,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            self.metrics.record_error("graph")
            return False

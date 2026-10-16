import logging
from uuid import UUID

from redis.asyncio import Redis

from app.risk.models import RiskSnapshot

from .keys import risk_cache_key
from .metrics import CacheMetrics
from .models import CachedRiskSnapshotDTO
from .serializer import (
    deserialize_model,
    dto_to_risk_snapshot,
    risk_snapshot_to_dto,
    serialize_model,
)

logger = logging.getLogger("floodguard.cache.risk")


class RiskSnapshotCache:
    """Cache-aside manager for deterministic RiskSnapshot evaluations."""

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
        risk_revision: int,
        config_hash: str,
    ) -> RiskSnapshot | None:
        if not self.enabled or self.redis is None:
            self.metrics.record_bypassed("risk")
            return None

        key = risk_cache_key(graph_version_id, risk_revision, config_hash)
        try:
            raw = await self.redis.get(key)
            if raw is None:
                self.metrics.record_miss("risk")
                return None

            dto = deserialize_model(raw, CachedRiskSnapshotDTO)
            if dto is None:
                self.metrics.record_miss("risk")
                return None

            snapshot = dto_to_risk_snapshot(dto)
            self.metrics.record_hit("risk")
            return snapshot
        except Exception as error:
            logger.warning(
                "risk_cache_read_error",
                extra={
                    "key": key,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            self.metrics.record_error("risk")
            return None

    async def set(
        self,
        graph_version_id: UUID | str,
        risk_revision: int,
        config_hash: str,
        snapshot: RiskSnapshot,
    ) -> bool:
        if not self.enabled or self.redis is None:
            return False

        key = risk_cache_key(graph_version_id, risk_revision, config_hash)
        try:
            dto = risk_snapshot_to_dto(graph_version_id, risk_revision, snapshot)
            payload = serialize_model(dto)
            await self.redis.set(key, payload, ex=self.ttl_seconds)
            self.metrics.record_set("risk")
            return True
        except Exception as error:
            logger.warning(
                "risk_cache_write_error",
                extra={
                    "key": key,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
            self.metrics.record_error("risk")
            return False

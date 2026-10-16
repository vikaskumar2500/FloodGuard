"""Redis-backed idempotency store guaranteeing at-least-once message deduplication.

Enforces CRITICAL INVARIANT 1:
SQS delivery is AT-LEAST-ONCE. Handlers MUST be idempotent.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from redis.asyncio import Redis

from app.cache.keys import idempotency_key

logger = logging.getLogger("floodguard.messaging.idempotency")


class IdempotencyStatus(StrEnum):
    ACQUIRED = "ACQUIRED"
    ALREADY_COMPLETED = "ALREADY_COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"


class IdempotencyStoreUnavailableError(Exception):
    """Raised when Redis idempotency store is unavailable and fallback mode is REJECT."""


class RedisIdempotencyStore:
    """Manages event processing leases and completion markers in Redis."""

    def __init__(
        self,
        redis: Redis | None,
        ttl_seconds: int = 86400,
        lease_seconds: int = 120,
        fallback_mode: Literal["DEGRADED_PROCESS", "REJECT"] = "DEGRADED_PROCESS",
    ) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.lease_seconds = lease_seconds
        self.fallback_mode = fallback_mode

    async def try_acquire(
        self, event_id: str, correlation_id: str = "", token: str = ""
    ) -> IdempotencyStatus:
        """Attempt to acquire a processing lease for an incoming event_id.

        Returns:
            ACQUIRED: Lease granted; first time seeing this event.
            ALREADY_COMPLETED: Event was already successfully processed.
            IN_PROGRESS: Event is currently being processed by another consumer worker.
        """
        if self.redis is None:
            if self.fallback_mode == "REJECT":
                raise IdempotencyStoreUnavailableError("Redis idempotency store is unavailable")
            logger.warning(
                "Redis unavailable for idempotency; degrading to un-deduplicated processing for event %s",
                event_id,
            )
            return IdempotencyStatus.ACQUIRED

        key = idempotency_key(event_id)
        now_iso = datetime.now(UTC).isoformat()
        lease_payload = json.dumps(
            {
                "state": "PROCESSING",
                "correlationId": correlation_id,
                "token": token,
                "acquiredAt": now_iso,
            }
        )

        try:
            # Atomic SETNX with lease TTL
            set_ok = await self.redis.set(key, lease_payload, ex=self.lease_seconds, nx=True)
            if set_ok:
                return IdempotencyStatus.ACQUIRED

            # Key already exists: inspect current state
            raw_val = await self.redis.get(key)
            if not raw_val:
                # Key expired between operations: retry acquisition
                retry_set = await self.redis.set(key, lease_payload, ex=self.lease_seconds, nx=True)
                return IdempotencyStatus.ACQUIRED if retry_set else IdempotencyStatus.IN_PROGRESS

            val_str = raw_val.decode("utf-8") if isinstance(raw_val, bytes) else str(raw_val)
            parsed = json.loads(val_str)
            state = parsed.get("state")
            if state == "COMPLETED":
                return IdempotencyStatus.ALREADY_COMPLETED
            return IdempotencyStatus.IN_PROGRESS

        except Exception as err:
            logger.error("Error communicating with Redis idempotency store: %s", err)
            if self.fallback_mode == "REJECT":
                raise IdempotencyStoreUnavailableError(str(err)) from err
            return IdempotencyStatus.ACQUIRED

    async def mark_completed(
        self, event_id: str, correlation_id: str = "", token: str = ""
    ) -> None:
        """Transition event status to COMPLETED with long retention TTL."""
        if self.redis is None:
            return

        key = idempotency_key(event_id)
        # Using Lua script to only mark completed if we hold the token
        script = """
        local current = redis.call("GET", KEYS[1])
        if current then
            local decoded = cjson.decode(current)
            if decoded.token == ARGV[2] or decoded.state == "COMPLETED" then
                redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[3])
                return 1
            end
            return 0
        end
        redis.call("SET", KEYS[1], ARGV[1], "EX", ARGV[3])
        return 1
        """
        import json
        from datetime import UTC, datetime

        payload = json.dumps(
            {
                "state": "COMPLETED",
                "correlationId": correlation_id,
                "completedAt": datetime.now(UTC).isoformat(),
            }
        )
        try:
            await self.redis.eval(script, 1, key, payload, token, self.ttl_seconds)
        except Exception as err:
            import logging

            logging.getLogger("floodguard.messaging.idempotency").error(
                "Failed to mark event %s as COMPLETED in Redis: %s", event_id, err
            )

    async def release(self, event_id: str, token: str = "") -> None:
        """Release processing lease on failure so message is immediately retryable upon redelivery."""
        if self.redis is None:
            return

        key = idempotency_key(event_id)
        script = """
        local current = redis.call("GET", KEYS[1])
        if current then
            local decoded = cjson.decode(current)
            if decoded.token == ARGV[1] then
                redis.call("DEL", KEYS[1])
                return 1
            end
            return 0
        end
        return 0
        """
        try:
            await self.redis.eval(script, 1, key, token)
        except Exception as err:
            import logging

            logging.getLogger("floodguard.messaging.idempotency").warning(
                "Failed to release idempotency key %s: %s", key, err
            )

    async def mark_dead_lettered(
        self, event_id: str, correlation_id: str = "", token: str = ""
    ) -> None:
        """Transition event status to DEAD_LETTERED with long retention TTL."""
        if self.redis is None:
            return

        key = idempotency_key(event_id)
        import json
        from datetime import UTC, datetime

        payload = json.dumps(
            {
                "state": "DEAD_LETTERED",
                "correlationId": correlation_id,
                "completedAt": datetime.now(UTC).isoformat(),
            }
        )
        try:
            await self.redis.set(key, payload, ex=self.ttl_seconds)
        except Exception:
            pass

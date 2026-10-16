import time

from fastapi import HTTPException, Request
from redis.asyncio import Redis

from app.core.config import get_settings

settings = get_settings()

# Fallback in-memory rate limiting when redis is not available
_in_memory_store: dict[str, list[float]] = {}


async def check_rate_limit(
    request: Request,
    redis_client: Redis | None,
    action: str,
    max_requests: int,
    window_seconds: int,
):
    if not settings.rate_limit_enabled:
        return

    # Get IP or User ID for rate limiting key
    client_ip = request.client.host if request.client else "unknown"
    user_id = getattr(request.state, "user_id", client_ip)

    key = f"rate_limit:{action}:{user_id}"
    current_time = time.time()

    if redis_client:
        try:
            # Redis Token Bucket / Window via zset or simple list
            pipeline = redis_client.pipeline()
            pipeline.zremrangebyscore(key, 0, current_time - window_seconds)
            pipeline.zadd(key, {str(current_time): current_time})
            pipeline.zcard(key)
            pipeline.expire(key, window_seconds)
            _, _, request_count, _ = await pipeline.execute()

            if request_count > max_requests:
                raise HTTPException(status_code=429, detail="Too many requests")
            return
        except HTTPException:
            raise
        except Exception:
            # Fallback to in-memory if Redis fails
            pass

    # In-memory fallback
    if key not in _in_memory_store:
        _in_memory_store[key] = []

    # Clean up old entries
    _in_memory_store[key] = [
        ts for ts in _in_memory_store[key] if ts > current_time - window_seconds
    ]

    if len(_in_memory_store[key]) >= max_requests:
        raise HTTPException(status_code=429, detail="Too many requests")

    _in_memory_store[key].append(current_time)

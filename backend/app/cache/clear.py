import asyncio
import logging
import sys
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.redis import create_redis_client

logger = logging.getLogger("floodguard.cache.clear")


async def clear_cache(
    redis: Redis, pattern: str = "floodguard:v1:*", batch_size: int = 100
) -> dict[str, Any]:
    """Safely clear keys matching pattern using cursor SCAN and batch delete.

    Never invokes FLUSHALL or FLUSHDB to protect shared Redis environments.
    """
    deleted_count = 0
    batch = []

    async for key in redis.scan_iter(match=pattern, count=batch_size):
        batch.append(key)
        if len(batch) >= batch_size:
            deleted_count += await redis.delete(*batch)
            batch = []

    if batch:
        deleted_count += await redis.delete(*batch)

    return {
        "pattern": pattern,
        "deleted_count": deleted_count,
    }


async def main() -> None:
    pattern = sys.argv[1] if len(sys.argv) > 1 else "floodguard:v1:*"
    settings = get_settings()
    redis = create_redis_client(settings)
    try:
        result = await clear_cache(redis, pattern=pattern)
        print(f"Cleared {result['deleted_count']} keys matching '{result['pattern']}'.")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())

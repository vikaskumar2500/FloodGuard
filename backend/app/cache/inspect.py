import asyncio
import json
import logging
from typing import Any

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.redis import create_redis_client

logger = logging.getLogger("floodguard.cache.inspect")


async def inspect_cache(redis: Redis, pattern: str = "floodguard:v1:*") -> dict[str, Any]:
    """Inspect cached keys using cursor SCAN (never KEYS *)."""
    keys = []
    async for key in redis.scan_iter(match=pattern, count=100):
        keys.append(key)

    items = []
    summary: dict[str, int] = {"graph": 0, "route": 0, "risk": 0, "other": 0}

    for key in keys:
        ttl = await redis.ttl(key)
        key_type = await redis.type(key)
        try:
            mem = await redis.memory_usage(key)
        except Exception:
            mem = None

        domain = "other"
        for candidate in ("graph", "route", "risk"):
            if f":{candidate}:" in key:
                domain = candidate
                break
        summary[domain] += 1

        items.append(
            {
                "key": key,
                "domain": domain,
                "type": key_type,
                "ttl_seconds": ttl,
                "memory_bytes": mem,
            }
        )

    return {
        "pattern": pattern,
        "total_keys": len(keys),
        "summary": summary,
        "keys": sorted(items, key=lambda x: x["key"]),
    }


async def main() -> None:
    settings = get_settings()
    redis = create_redis_client(settings)
    try:
        report = await inspect_cache(redis)
        print(json.dumps(report, indent=2))
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())

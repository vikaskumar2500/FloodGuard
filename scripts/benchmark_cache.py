import asyncio
import time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.health import DependencyHealth
class RedisConnectionError(Exception):
    pass

class InMemoryFakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.error_on_get = False
        self.error_on_set = False

    async def get(self, key: str) -> str | None:
        if self.error_on_get:
            raise RedisConnectionError("Fake connection failure")
        return self.storage.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if self.error_on_set:
            raise RedisConnectionError("Fake connection failure")
        self.storage[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass

    async def aclose(self) -> None:
        pass


def benchmark():
    import unittest.mock as mock
    settings = Settings(
        app_env="test",
        use_fixture_routing=True,
        cache_enabled=True,
        redis_required=False,
    )
    fake_redis = InMemoryFakeRedis()
    
    with mock.patch("app.main.create_redis_client", return_value=fake_redis):
        app = create_app(settings)
        body = {
            "source": {"longitude": 0, "latitude": 0},
            "destination": {"longitude": 0.003, "latitude": 0},
            "mode": "SAFEST",
            "algorithm": "ASTAR",
        }
        with TestClient(app) as client:
            # 1. Cold execution (MISS)
            t0 = time.perf_counter()
            res_cold = client.post("/api/v1/routes/calculate", json=body)
            t_cold = (time.perf_counter() - t0) * 1000

            assert res_cold.status_code == 201
            assert res_cold.headers["x-floodguard-cache"] == "MISS"

            # 2. Warm cache execution (HIT)
            warm_times = []
            for _ in range(50):
                t1 = time.perf_counter()
                res_warm = client.post("/api/v1/routes/calculate", json=body)
                warm_times.append((time.perf_counter() - t1) * 1000)
                assert res_warm.headers["x-floodguard-cache"] == "HIT"

            avg_warm = sum(warm_times) / len(warm_times)
            min_warm = min(warm_times)
            speedup = t_cold / avg_warm if avg_warm > 0 else 1.0

            metrics = app.state.cache_metrics.snapshot()

            import json
            from pathlib import Path
            print(f"\n=== FloodGuard Phase 9 Caching Benchmark ===")
            print(f"Cold route latency (MISS):  {t_cold:.3f} ms")
            print(f"Warm route latency (HIT):   {avg_warm:.3f} ms (min: {min_warm:.3f} ms)")
            print(f"Speedup:                    {speedup:.1f}x")
            print(f"Route Cache Hits:           {metrics['domains']['route']['hits']}")
            print(f"Route Cache Misses:         {metrics['domains']['route']['misses']}")
            print(f"Overall Hit Ratio:          {metrics['overall']['hit_ratio'] * 100:.1f}%\n")
            
            out_dir = Path(__file__).resolve().parent.parent / "performance" / "reports"
            out_dir.mkdir(parents=True, exist_ok=True)
            with open(out_dir / "caching.json", "w") as f:
                json.dump({
                    "cold_latency_ms": t_cold,
                    "warm_latency_avg_ms": avg_warm,
                    "warm_latency_min_ms": min_warm,
                    "speedup": speedup,
                    "route_hits": metrics['domains']['route']['hits'],
                    "route_misses": metrics['domains']['route']['misses'],
                    "overall_hit_ratio": metrics['overall']['hit_ratio']
                }, f, indent=2)


if __name__ == "__main__":
    benchmark()

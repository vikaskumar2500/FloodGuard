import asyncio
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

class ChaosFakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.error_on_get = False
        self.error_on_set = False

    async def get(self, key: str) -> str | None:
        if self.error_on_get:
            raise Exception("Fake connection failure")
        return self.storage.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if self.error_on_set:
            raise Exception("Fake connection failure")
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

def generate_report():
    print("Running Chaos Experiments...")
    import unittest.mock as mock
    from app.core.config import Settings
    from app.main import create_app
    from starlette.testclient import TestClient

    settings = Settings(
        app_env="test",
        use_fixture_routing=True,
        cache_enabled=True,
        redis_required=False,
    )
    
    chaos_redis = ChaosFakeRedis()
    
    with mock.patch("app.main.create_redis_client", return_value=chaos_redis):
        app = create_app(settings)
        
        with TestClient(app) as client:
            body = {
                "source": {"longitude": 0, "latitude": 0},
                "destination": {"longitude": 0.003, "latitude": 0},
                "mode": "SAFEST",
                "algorithm": "ASTAR",
            }
            res_baseline = client.post("/api/v1/routes/calculate", json=body)
            assert res_baseline.status_code == 201
            print("Baseline route success:", res_baseline.status_code)
            
            chaos_redis.error_on_get = True
            chaos_redis.error_on_set = True
            
            res_fault = client.post("/api/v1/routes/calculate", json=body)
            assert res_fault.status_code == 201 
            assert res_fault.headers.get("x-floodguard-cache") == "MISS"
            print("Redis fault route success:", res_fault.status_code)
            
            chaos_redis.error_on_get = False
            chaos_redis.error_on_set = False
            client.post("/api/v1/routes/calculate", json=body) # Cache it
            res_recover = client.post("/api/v1/routes/calculate", json=body)
            assert res_recover.status_code == 201
            assert res_recover.headers.get("x-floodguard-cache") == "HIT"
            print("Redis recovery route success, cache hit restored.")

if __name__ == "__main__":
    generate_report()

import time

import pytest
from fastapi import HTTPException

from app.core.rate_limit import _in_memory_store, check_rate_limit


class MockRequest:
    def __init__(self, ip="127.0.0.1"):
        class Client:
            host = ip

        self.client = Client()

        class State:
            user_id = ip

        self.state = State()


@pytest.fixture(autouse=True)
def clean_in_memory_store():
    _in_memory_store.clear()
    yield
    _in_memory_store.clear()


@pytest.mark.asyncio
async def test_rate_limit_exceeded(monkeypatch):
    mock_time = 1000.0

    def fake_time():
        return mock_time

    monkeypatch.setattr(time, "time", fake_time)

    req = MockRequest()
    # 2 max requests per 60s
    await check_rate_limit(req, None, "test_action", 2, 60)
    await check_rate_limit(req, None, "test_action", 2, 60)

    with pytest.raises(HTTPException) as exc:
        await check_rate_limit(req, None, "test_action", 2, 60)
    assert exc.value.status_code == 429

    # advance time
    mock_time += 61.0
    # should succeed now
    await check_rate_limit(req, None, "test_action", 2, 60)


@pytest.mark.asyncio
async def test_rate_limit_redis(monkeypatch):
    mock_time = 1000.0

    def fake_time():
        return mock_time

    monkeypatch.setattr(time, "time", fake_time)

    class MockPipeline:
        def __init__(self):
            self.count = 0

        def zremrangebyscore(self, key, min, max):
            pass

        def zadd(self, key, mapping):
            self.count += 1

        def zcard(self, key):
            pass

        def expire(self, key, time):
            pass

        async def execute(self):
            return [None, None, self.count, None]

    class MockRedis:
        def __init__(self):
            self.pipe = MockPipeline()

        def pipeline(self):
            return self.pipe

    redis = MockRedis()
    req = MockRequest()

    await check_rate_limit(req, redis, "test_redis", 2, 60)
    await check_rate_limit(req, redis, "test_redis", 2, 60)

    with pytest.raises(HTTPException) as exc:
        await check_rate_limit(req, redis, "test_redis", 2, 60)
    assert exc.value.status_code == 429

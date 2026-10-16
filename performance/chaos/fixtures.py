import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "backend"))

from app.messaging.sqs.client import InMemorySqsTransport
from tests.unit.test_cache import InMemoryFakeRedis
from performance.chaos.controller import get_chaos_controller

class ChaosFakeRedis(InMemoryFakeRedis):
    async def get(self, key: str) -> str | None:
        ctrl = get_chaos_controller()
        res = await ctrl.maybe_fault("redis")
        if res is not None:
            return res
        return await super().get(key)
        
    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        ctrl = get_chaos_controller()
        await ctrl.maybe_fault("redis_set")
        return await super().set(key, value, ex)
        
class ChaosSqsTransport(InMemorySqsTransport):
    async def send_message(self, *args, **kwargs):
        ctrl = get_chaos_controller()
        await ctrl.maybe_fault("sqs_publish")
        return await super().send_message(*args, **kwargs)
        
    async def receive_messages(self, *args, **kwargs):
        ctrl = get_chaos_controller()
        await ctrl.maybe_fault("sqs_receive")
        return await super().receive_messages(*args, **kwargs)

    async def delete_message(self, *args, **kwargs):
        ctrl = get_chaos_controller()
        await ctrl.maybe_fault("sqs_delete")
        return await super().delete_message(*args, **kwargs)


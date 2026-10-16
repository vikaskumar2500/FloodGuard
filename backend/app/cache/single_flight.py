import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger("floodguard.cache.single_flight")
T = TypeVar("T")


class SingleFlight:
    """Coalesces concurrent requests for the same key into a single execution.

    Prevents cache stampedes / thundering herd by ensuring only one computation
    runs concurrently for a given cache key.
    """

    def __init__(self) -> None:
        self._calls: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()

    async def execute(self, key: str, action: Callable[[], Awaitable[T]]) -> T:
        is_leader = False
        async with self._lock:
            if key in self._calls:
                future = self._calls[key]
            else:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                self._calls[key] = future
                is_leader = True

        if is_leader:
            try:
                result = await action()
                if not future.done():
                    future.set_result(result)
                return result
            except BaseException as exc:
                if not future.done():
                    future.set_exception(exc)
                raise
            finally:
                async with self._lock:
                    self._calls.pop(key, None)
        else:
            return await asyncio.shield(future)

import inspect
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable[[dict[str, Any]], None]]] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        callback: Callable[[dict[str, Any]], None],
    ) -> Callable[[], None]:
        self._subs[event_type].append(callback)

        def unsubscribe() -> None:
            self._subs[event_type] = [
                handler for handler in self._subs[event_type] if handler is not callback
            ]

        return unsubscribe

    def publish(self, event: dict[str, Any]) -> None:
        for callback in list(self._subs.get(event.get("eventType", ""), ())):
            callback(event)

    async def publish_async(self, event: dict[str, Any]) -> None:
        for callback in list(self._subs.get(event.get("eventType", ""), ())):
            result = callback(event)
            if inspect.isawaitable(result):
                await result

    def reset(self) -> None:
        self._subs.clear()

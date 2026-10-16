import asyncio
from collections import defaultdict
from uuid import UUID

from .events import HeartbeatData, RealtimeEvent, RealtimeEventType


class RealtimePublisher:
    """Non-blocking, route-scoped fan-out with monotonic per-route sequences."""

    def __init__(self, queue_size: int = 16) -> None:
        self.queue_size = queue_size
        self._subscribers: dict[str, list[asyncio.Queue[RealtimeEvent]]] = defaultdict(list)
        self._sequences: dict[str, int] = defaultdict(int)

    def subscribe(self, route_id: str) -> asyncio.Queue[RealtimeEvent]:
        queue: asyncio.Queue[RealtimeEvent] = asyncio.Queue(maxsize=self.queue_size)
        self._subscribers[route_id].append(queue)
        return queue

    def unsubscribe(self, route_id: str, queue: asyncio.Queue[RealtimeEvent]) -> None:
        subscribers = self._subscribers.get(route_id)
        if not subscribers:
            return
        if queue in subscribers:
            subscribers.remove(queue)
        if not subscribers:
            self._subscribers.pop(route_id, None)

    def publish(
        self, route_id: str, event_type: RealtimeEventType, data: object, *, risk_revision: int
    ) -> RealtimeEvent:
        self._sequences[route_id] += 1
        event = RealtimeEvent(
            eventType=event_type,
            routeId=UUID(route_id),
            sequence=self._sequences[route_id],
            riskRevision=risk_revision,
            data=data,
        )
        for queue in list(self._subscribers.get(route_id, ())):
            self._offer(queue, event)
        return event

    def heartbeat(self, route_id: str, risk_revision: int) -> RealtimeEvent:
        return self.publish(route_id, "heartbeat", HeartbeatData(), risk_revision=risk_revision)

    def close_all(self) -> None:
        self._subscribers.clear()

    @staticmethod
    def encode(event: RealtimeEvent) -> str:
        return (
            f"id: {event.sequence}\nevent: {event.eventType}\ndata: {event.model_dump_json()}\n\n"
        )

    @staticmethod
    def _offer(queue: asyncio.Queue[RealtimeEvent], event: RealtimeEvent) -> None:
        if not queue.full():
            queue.put_nowait(event)
            return
        buffered: list[RealtimeEvent] = []
        while not queue.empty():
            buffered.append(queue.get_nowait())
        if event.eventType == "route.risk_updated":
            buffered = [item for item in buffered if item.eventType != "route.risk_updated"]
        if len(buffered) >= queue.maxsize:
            drop = next(
                (
                    i
                    for i, item in enumerate(buffered)
                    if item.eventType in {"heartbeat", "route.risk_updated"}
                ),
                0,
            )
            buffered.pop(drop)
        for item in buffered:
            queue.put_nowait(item)
        queue.put_nowait(event)

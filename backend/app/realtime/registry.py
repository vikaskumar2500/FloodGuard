import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger("floodguard.realtime")


@dataclass(frozen=True)
class ActiveRoute:
    route_id: str
    graph_version_id: str
    mode: str
    source: tuple[float, float]
    destination: tuple[float, float]
    edge_ids: list[str]
    risk_score: float
    risk_level: str
    current_eta_s: float
    risk_confidence: float = 0.0
    evaluated_risk_revision: int = 0
    unsafe_latched: bool = False
    last_rerouted_at: datetime | None = None
    created_at: datetime | None = None
    user_id: str | None = None
    expires_at: datetime | None = None
    metadata: dict[str, Any] | None = None


class ActiveRouteRegistry:
    def __init__(
        self, *, clock: Callable[[], datetime] | None = None, ttl_seconds: float = 900
    ) -> None:
        self._routes: dict[str, ActiveRoute] = {}
        self._edge_index: dict[str, set[str]] = {}
        self.clock = clock or (lambda: datetime.now(UTC))
        self.ttl = timedelta(seconds=ttl_seconds)

    def register(self, route: ActiveRoute) -> None:
        now = self.clock()
        if route.created_at is None or route.expires_at is None:
            route = replace(
                route,
                created_at=route.created_at or now,
                expires_at=route.expires_at or now + self.ttl,
            )
        self.unregister(route.route_id)
        self._routes[route.route_id] = route
        for edge_id in route.edge_ids:
            self._edge_index.setdefault(edge_id, set()).add(route.route_id)

    def update(self, route_id: str, **changes: Any) -> ActiveRoute:
        route = replace(self._routes[route_id], **changes)
        self.register(route)
        return route

    def replace(self, old_route_id: str, route: ActiveRoute) -> None:
        self.unregister(old_route_id)
        self.register(route)

    def unregister(self, route_id: str) -> None:
        route = self._routes.pop(route_id, None)
        if route is None:
            return
        for edge_id in route.edge_ids:
            routes = self._edge_index.get(edge_id)
            if routes is None:
                continue
            routes.discard(route_id)
            if not routes:
                self._edge_index.pop(edge_id, None)

    def get(self, route_id: str) -> ActiveRoute | None:
        route = self._routes.get(route_id)
        if route and route.expires_at and route.expires_at <= self.clock():
            self.unregister(route_id)
            logger.info("route_expired", extra={"route_id": route_id})
            return None
        return route

    def clear(self) -> None:
        self._routes.clear()
        self._edge_index.clear()

    def routes_using_edges(self, edge_ids: set[str]) -> set[str]:
        result: set[str] = set()
        for edge_id in edge_ids:
            result.update(self._edge_index.get(edge_id, set()))
        return result

from collections.abc import Mapping
from uuid import UUID

from .dijkstra import _search
from .heuristics import travel_time_heuristic
from .models import PathResult, RoutingGraph


def find_path(
    graph: RoutingGraph,
    source_node_id: UUID,
    destination_node_id: UUID,
    *,
    max_expansions: int | None = None,
    costs: Mapping[UUID, float] | None = None,
) -> PathResult:
    return _search(
        graph,
        source_node_id,
        destination_node_id,
        heuristic=lambda node_id: travel_time_heuristic(graph, node_id, destination_node_id),
        max_expansions=max_expansions,
        costs=costs,
    )

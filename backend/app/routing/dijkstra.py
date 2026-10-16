from collections.abc import Mapping
from heapq import heappop, heappush
from itertools import count
from math import inf
from uuid import UUID

from .exceptions import RoutingExpansionLimitExceeded
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
        heuristic=lambda _node_id: 0.0,
        max_expansions=max_expansions,
        costs=costs,
    )


def _search(graph, source_node_id, destination_node_id, heuristic, max_expansions, costs):
    if source_node_id not in graph.nodes or destination_node_id not in graph.nodes:
        return PathResult.not_found(0)
    if source_node_id == destination_node_id:
        return PathResult(True, (), (source_node_id,), 0.0, 0)
    distances = {source_node_id: 0.0}
    predecessor_edges: dict[UUID, UUID] = {}
    predecessor_nodes: dict[UUID, UUID] = {}
    queue: list[tuple[float, int, UUID, float]] = []
    sequence = count()
    heappush(queue, (0.0, next(sequence), source_node_id, 0.0))
    expanded = 0
    while queue:
        _, _, current, current_cost = heappop(queue)
        if current_cost != distances.get(current, inf):
            continue
        if max_expansions is not None and expanded >= max_expansions:
            raise RoutingExpansionLimitExceeded("routing expansion limit exceeded")
        expanded += 1
        if current == destination_node_id:
            return _reconstruct(
                source_node_id,
                destination_node_id,
                predecessor_edges,
                predecessor_nodes,
                current_cost,
                expanded,
            )
        for edge in graph.adjacency.get(current, ()):
            edge_cost = edge.base_travel_time_s if costs is None else costs[edge.id]
            candidate = current_cost + edge_cost
            if candidate < distances.get(edge.target, inf):
                distances[edge.target] = candidate
                predecessor_edges[edge.target] = edge.id
                predecessor_nodes[edge.target] = current
                heappush(
                    queue,
                    (
                        candidate + heuristic(edge.target),
                        next(sequence),
                        edge.target,
                        candidate,
                    ),
                )
    return PathResult.not_found(expanded)


def _reconstruct(source, destination, predecessor_edges, predecessor_nodes, cost, expanded):
    edge_ids: list[UUID] = []
    node_ids: list[UUID] = [destination]
    current = destination
    while current != source:
        edge_ids.append(predecessor_edges[current])
        current = predecessor_nodes[current]
        node_ids.append(current)
    edge_ids.reverse()
    node_ids.reverse()
    return PathResult(True, tuple(edge_ids), tuple(node_ids), cost, expanded)

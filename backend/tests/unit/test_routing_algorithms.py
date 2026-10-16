from uuid import UUID, uuid5

import pytest

from app.routing.astar import find_path as astar
from app.routing.dijkstra import find_path as dijkstra
from app.routing.exceptions import RoutingExpansionLimitExceeded
from app.routing.heuristics import travel_time_heuristic
from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode, assemble_geometry

NAMESPACE = UUID("7a1d88f0-6e4c-4d1b-b45f-6e8e3696e415")


def node(name: str) -> UUID:
    return uuid5(NAMESPACE, name)


def graph_with_edges(edges: list[tuple[str, str, float, float]]) -> RoutingGraph:
    graph = RoutingGraph()
    coordinates = {name: (index * 0.000001, 0.0) for index, name in enumerate("ABCDEFGH")}
    for name, coordinate in coordinates.items():
        graph.add_node(RoutingNode(node(name), coordinate))
    for index, (source, target, distance, travel_time) in enumerate(edges):
        graph.add_edge(
            RoutingEdge(
                node(f"edge-{index}"),
                node(source),
                node(target),
                distance,
                travel_time,
                (coordinates[source], coordinates[target]),
            )
        )
    graph.validate()
    return graph


def test_dijkstra_selects_expected_competing_path_and_edge_sequence():
    graph = graph_with_edges(
        [("A", "B", 1, 1), ("B", "D", 1, 1), ("A", "C", 5, 5), ("C", "D", 1, 1)]
    )
    result = dijkstra(graph, node("A"), node("D"))

    assert result.found
    assert result.node_ids == (node("A"), node("B"), node("D"))
    assert result.total_cost == 2
    assert len(result.edge_ids) == 2


def test_algorithms_handle_cycles_one_way_parallel_edges_and_unreachable_nodes():
    graph = graph_with_edges(
        [
            ("A", "B", 1, 1),
            ("B", "A", 1, 1),
            ("B", "C", 1, 1),
            ("A", "C", 5, 5),
            ("A", "C", 2, 2),
        ]
    )
    result = dijkstra(graph, node("A"), node("C"))
    unreachable = dijkstra(graph, node("C"), node("A"))

    assert result.found and result.total_cost == 2
    assert unreachable.found is False
    assert unreachable.edge_ids == ()


def test_source_equals_destination_is_zero_cost():
    graph = graph_with_edges([("A", "B", 1, 1)])

    result = astar(graph, node("A"), node("A"))

    assert result.found
    assert result.node_ids == (node("A"),)
    assert result.edge_ids == ()
    assert result.total_cost == 0


def test_effective_speed_bound_uses_distance_over_baseline_time():
    graph = graph_with_edges([("A", "B", 10, 2)])

    assert graph.max_speed_mps == 5


def test_astar_matches_dijkstra_and_heuristic_is_safe():
    graph = graph_with_edges(
        [("A", "B", 1, 1), ("B", "D", 1, 1), ("A", "C", 5, 5), ("C", "D", 1, 1)]
    )
    dijkstra_result = dijkstra(graph, node("A"), node("D"))
    astar_result = astar(graph, node("A"), node("D"))

    assert astar_result.total_cost == pytest.approx(dijkstra_result.total_cost)
    assert travel_time_heuristic(graph, node("D"), node("D")) == 0
    assert travel_time_heuristic(graph, node("A"), node("D")) >= 0
    assert travel_time_heuristic(graph, node("A"), node("D")) <= dijkstra_result.total_cost


def test_geometry_assembly_removes_shared_coordinates():
    graph = graph_with_edges([("A", "B", 1, 1), ("B", "C", 1, 1)])
    result = dijkstra(graph, node("A"), node("C"))
    geometry = assemble_geometry(graph, result.edge_ids)

    assert geometry.type == "LineString"
    assert geometry.coordinates == ((0.0, 0.0), (0.000001, 0.0), (0.000002, 0.0))


def test_expansion_limit_is_controlled():
    graph = graph_with_edges([("A", "B", 1, 1), ("B", "C", 1, 1)])

    with pytest.raises(RoutingExpansionLimitExceeded):
        dijkstra(graph, node("A"), node("C"), max_expansions=1)

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

import pytest

from app.risk.config import RiskConfig
from app.risk.costs import build_edge_costs
from app.risk.models import EdgeEvidence, FloodZoneEvidence
from app.risk.normalization import freshness_weight, normalize_measurement
from app.risk.service import evaluate_graph
from app.routing.astar import find_path as astar
from app.routing.dijkstra import find_path as dijkstra
from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode

NAMESPACE = UUID("26d95d3c-3ce8-40f0-8c27-23a6d593f70b")
NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


def identifier(name: str) -> UUID:
    return uuid5(NAMESPACE, name)


def risk_graph() -> tuple[RoutingGraph, dict[str, UUID]]:
    graph = RoutingGraph()
    coordinates = {
        "A": (0.0, 0.0),
        "B": (0.001, 0.0),
        "C": (0.002, 0.0),
        "E": (0.0, 0.001),
        "F": (0.0015, 0.001),
        "D": (0.003, 0.0),
    }
    nodes = {name: identifier(f"node-{name}") for name in coordinates}
    for name, coordinate in coordinates.items():
        graph.add_node(RoutingNode(nodes[name], coordinate))
    edges = [
        ("AB", "A", "B", 1, 1),
        ("BC", "B", "C", 1, 1),
        ("CD", "C", "D", 1, 1),
        ("AE", "A", "E", 2, 2),
        ("EF", "E", "F", 2, 2),
        ("FD", "F", "D", 2, 2),
    ]
    for name, source, target, distance, travel_time in edges:
        graph.add_edge(
            RoutingEdge(
                identifier(f"edge-{name}"),
                nodes[source],
                nodes[target],
                distance,
                travel_time,
                (coordinates[source], coordinates[target]),
            )
        )
    graph.validate()
    return graph, nodes


def test_normalization_and_freshness_boundaries():
    assert normalize_measurement(0, (5, 15, 30, 50)) == 0
    assert normalize_measurement(50, (5, 15, 30, 50)) == 1
    assert normalize_measurement(100, (5, 15, 30, 50)) == 1
    assert freshness_weight(NOW, NOW, timedelta(hours=2)) == 1
    assert freshness_weight(NOW - timedelta(hours=3), NOW, timedelta(hours=2)) == 0
    with pytest.raises(ValueError):
        normalize_measurement(float("nan"), (5, 15, 30, 50))
    with pytest.raises(ValueError):
        normalize_measurement(-1, (5, 15, 30, 50))
    with pytest.raises(ValueError):
        RiskConfig(flood_zone_weight=-1)


def test_modes_choose_different_paths_when_flood_evidence_justifies_it():
    graph, nodes = risk_graph()
    top_edges = [
        edge
        for edge in graph.edges.values()
        if edge.geometry[0][1] == 0 and edge.geometry[1][1] == 0
    ]
    evidence = {
        edge.id: EdgeEvidence(
            flood_zones=[FloodZoneEvidence(1.0, 1.0, "SEVERE", timedelta(minutes=5))]
        )
        for edge in top_edges
    }
    config = RiskConfig(balanced_penalty_seconds=1.0)
    snapshot = evaluate_graph(graph, evidence, NOW, config)
    fastest = dijkstra(
        graph,
        nodes["A"],
        nodes["D"],
        costs=build_edge_costs(graph, snapshot.assessments, "FASTEST", config),
    )
    balanced = dijkstra(
        graph,
        nodes["A"],
        nodes["D"],
        costs=build_edge_costs(graph, snapshot.assessments, "BALANCED", config),
    )
    safest = dijkstra(
        graph,
        nodes["A"],
        nodes["D"],
        costs=build_edge_costs(graph, snapshot.assessments, "SAFEST", config),
    )
    safest_astar = astar(
        graph,
        nodes["A"],
        nodes["D"],
        costs=build_edge_costs(graph, snapshot.assessments, "SAFEST", config),
    )

    assert fastest.node_ids == (nodes["A"], nodes["B"], nodes["C"], nodes["D"])
    assert balanced.node_ids == fastest.node_ids
    assert safest.node_ids == (nodes["A"], nodes["E"], nodes["F"], nodes["D"])
    assert safest_astar.total_cost == pytest.approx(safest.total_cost)
    assert snapshot.assessments[top_edges[0].id].risk_score >= 0.75
    assert snapshot.assessments[top_edges[0].id].confidence > 0


def test_no_evidence_is_unknown_not_confidently_safe():
    graph, _ = risk_graph()
    snapshot = evaluate_graph(graph, {}, NOW, RiskConfig())

    assert all(assessment.risk_score == 0 for assessment in snapshot.assessments.values())
    assert all(assessment.confidence == 0 for assessment in snapshot.assessments.values())
    assert all(
        "confidence is 0%" in assessment.explanation for assessment in snapshot.assessments.values()
    )


def test_no_risk_evidence_keeps_all_modes_on_the_baseline_path():
    graph, nodes = risk_graph()
    snapshot = evaluate_graph(graph, {}, NOW, RiskConfig())

    paths = [
        dijkstra(
            graph,
            nodes["A"],
            nodes["D"],
            costs=build_edge_costs(graph, snapshot.assessments, mode, RiskConfig()),
        ).node_ids
        for mode in ("FASTEST", "BALANCED", "SAFEST")
    ]

    assert paths[0] == paths[1] == paths[2]


def test_severe_risk_does_not_break_a_route_without_an_alternative():
    graph, nodes = risk_graph()
    graph.edges = {
        edge_id: edge
        for edge_id, edge in graph.edges.items()
        if edge.geometry[0][1] == 0 and edge.geometry[1][1] == 0
    }
    graph.adjacency = {
        node_id: [edge for edge in edges if edge.id in graph.edges]
        for node_id, edges in graph.adjacency.items()
    }
    top_edges = [
        edge
        for edge in graph.edges.values()
        if edge.geometry[0][1] == 0 and edge.geometry[1][1] == 0
    ]
    evidence = {
        edge.id: EdgeEvidence(
            flood_zones=[FloodZoneEvidence(1.0, 1.0, "SEVERE", timedelta(minutes=5))]
        )
        for edge in top_edges
    }
    snapshot = evaluate_graph(graph, evidence, NOW, RiskConfig())
    costs = build_edge_costs(graph, snapshot.assessments, "SAFEST", RiskConfig())
    result = dijkstra(graph, nodes["A"], nodes["D"], costs=costs)

    assert result.found
    assert result.node_ids == (nodes["A"], nodes["B"], nodes["C"], nodes["D"])


def test_expired_zone_is_ignored_and_astar_matches_dijkstra():
    graph, nodes = risk_graph()
    edge = next(iter(graph.edges.values()))
    snapshot = evaluate_graph(graph, {}, NOW, RiskConfig())
    costs = build_edge_costs(graph, snapshot.assessments, "SAFEST", RiskConfig())
    dijkstra_result = dijkstra(graph, nodes["A"], nodes["D"], costs=costs)
    astar_result = astar(graph, nodes["A"], nodes["D"], costs=costs)

    assert snapshot.assessments[edge.id].risk_score == 0
    assert astar_result.total_cost == pytest.approx(dijkstra_result.total_cost)

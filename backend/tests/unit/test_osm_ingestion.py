from pathlib import Path

import pytest

from app.ingestion.osm.filters import DEFAULT_SPEED_KPH, parse_oneway, speed_limit_kph
from app.ingestion.osm.graph_builder import build_graph
from app.ingestion.osm.models import OSMNode, OSMWay
from app.ingestion.osm.parser import parse_osm_xml
from app.ingestion.osm.service import load_graph

FIXTURE = Path(__file__).parents[1] / "fixtures" / "tiny.osm"


def test_fixture_parses_and_builds_directed_segments():
    nodes, ways, bounds = parse_osm_xml(FIXTURE)
    graph = build_graph(nodes, ways)

    assert len(nodes) == 8
    assert len(ways) == 8
    assert bounds == (0.0, 0.0, 0.003, 0.002)
    assert len(graph.nodes) == 8
    assert len(graph.edges) == 12
    assert graph.stats.accepted_road_ways == 6
    assert graph.stats.excluded_road_ways == 1
    assert graph.stats.restricted_roads_skipped == 1
    assert graph.stats.one_way_ways == 3
    assert graph.stats.two_way_ways == 3
    assert graph.stats.malformed_speed_tags == 1
    assert graph.stats.weakly_connected_components == 2
    assert graph.stats.largest_component_percent == 75


def test_direction_and_geometry_are_oriented():
    graph, _ = load_graph(FIXTURE)
    edges = {(edge.osm_way_id, edge.segment_index, edge.direction): edge for edge in graph.edges}

    assert (100, 0, 1) in edges
    assert (100, 0, -1) in edges
    assert (101, 0, 1) in edges
    assert (101, 0, -1) not in edges
    assert edges[(102, 0, -1)].source_osm_node_id == 4
    assert edges[(102, 0, -1)].target_osm_node_id == 3
    assert edges[(102, 0, -1)].is_one_way
    assert edges[(102, 0, -1)].coordinates[0] == (0.001, 0.001)
    assert edges[(104, 0, 1)].target_osm_node_id == 5
    assert edges[(104, 1, 1)].source_osm_node_id == 5
    assert all(edge.distance_m > 0 and edge.base_travel_time_s > 0 for edge in graph.edges)


def test_filtering_and_speed_rules():
    _, ways, _ = parse_osm_xml(FIXTURE)
    by_id = {way.osm_id: way for way in ways}

    assert parse_oneway(by_id[104]) == 1
    assert speed_limit_kph(by_id[102])[0] == pytest.approx(30 * 1.609344)
    assert speed_limit_kph(by_id[103]) == (DEFAULT_SPEED_KPH["tertiary"], True)


def test_invalid_segments_are_counted_and_missing_nodes_are_not_persisted():
    nodes = {1: OSMNode(1, 0, 0), 2: OSMNode(2, 0.001, 0)}
    ways = [
        OSMWay(1, (1, 1), {"highway": "residential"}),
        OSMWay(2, (1, 99), {"highway": "residential"}),
        OSMWay(3, (1, 2), {"highway": "residential"}),
    ]

    graph = build_graph(nodes, ways)

    assert graph.stats.invalid_segments_skipped == 2
    assert len(graph.edges) == 2
    assert {node.osm_id for node in graph.nodes} == {1, 2}

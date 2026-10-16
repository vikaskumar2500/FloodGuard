from math import asin, cos, radians, sin, sqrt

from .filters import is_access_restricted, is_drivable, metadata_for, parse_oneway, speed_limit_kph
from .models import Coordinate, GraphEdge, GraphNode, GraphStats, ImportGraph, OSMNode, OSMWay

EARTH_RADIUS_M = 6_371_008.8


def distance_m(first: Coordinate, second: Coordinate) -> float:
    first_lon, first_lat = map(radians, first)
    second_lon, second_lat = map(radians, second)
    delta_lat = second_lat - first_lat
    delta_lon = second_lon - first_lon
    value = sin(delta_lat / 2) ** 2 + cos(first_lat) * cos(second_lat) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(value))


def _boundary(nodes: list[GraphNode]) -> tuple[Coordinate, ...]:
    longitudes = [node.coordinate[0] for node in nodes]
    latitudes = [node.coordinate[1] for node in nodes]
    min_lon, max_lon = min(longitudes), max(longitudes)
    min_lat, max_lat = min(latitudes), max(latitudes)
    if min_lon == max_lon:
        min_lon -= 0.00001
        max_lon += 0.00001
    if min_lat == max_lat:
        min_lat -= 0.00001
        max_lat += 0.00001
    return (
        (min_lon, min_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
        (min_lon, max_lat),
        (min_lon, min_lat),
    )


def _connectivity(
    nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...], stats: GraphStats
) -> None:
    parents = {node.osm_id: node.osm_id for node in nodes}

    def find(node_id: int) -> int:
        while parents[node_id] != node_id:
            parents[node_id] = parents[parents[node_id]]
            node_id = parents[node_id]
        return node_id

    for edge in edges:
        left, right = find(edge.source_osm_node_id), find(edge.target_osm_node_id)
        if left != right:
            parents[right] = left
    sizes: dict[int, int] = {}
    for node_id in parents:
        root = find(node_id)
        sizes[root] = sizes.get(root, 0) + 1
    stats.weakly_connected_components = len(sizes)
    stats.largest_component_percent = max(sizes.values(), default=0) / max(len(nodes), 1) * 100


def build_graph(nodes: dict[int, OSMNode], ways: list[OSMWay]) -> ImportGraph:
    stats = GraphStats(osm_nodes_read=len(nodes), osm_ways_read=len(ways))
    retained_node_ids: set[int] = set()
    edges: list[GraphEdge] = []
    for way in ways:
        if not is_drivable(way):
            if is_access_restricted(way):
                stats.restricted_roads_skipped += 1
            else:
                stats.excluded_road_ways += 1
            continue
        stats.accepted_road_ways += 1
        traversal = parse_oneway(way)
        speed, malformed_speed = speed_limit_kph(way)
        stats.malformed_speed_tags += int(malformed_speed)
        stats.one_way_ways += int(traversal != 0)
        stats.two_way_ways += int(traversal == 0)
        way_metadata = metadata_for(way)
        for segment_index, (source_id, target_id) in enumerate(
            zip(way.node_ids, way.node_ids[1:], strict=False)
        ):
            if source_id == target_id or source_id not in nodes or target_id not in nodes:
                stats.invalid_segments_skipped += 1
                continue
            source, target = nodes[source_id], nodes[target_id]
            coordinates = ((source.longitude, source.latitude), (target.longitude, target.latitude))
            segment_distance = distance_m(coordinates[0], coordinates[1])
            if segment_distance <= 0:
                stats.invalid_segments_skipped += 1
                continue
            travel_time = segment_distance / (speed * 1000 / 3600)
            retained_node_ids.update((source_id, target_id))
            if traversal >= 0:
                edges.append(
                    GraphEdge(
                        way.osm_id,
                        segment_index,
                        1,
                        source_id,
                        target_id,
                        coordinates,
                        segment_distance,
                        travel_time,
                        way.tags["highway"].lower(),
                        speed,
                        traversal != 0,
                        way_metadata,
                    )
                )
            if traversal <= 0:
                reverse_coordinates = tuple(reversed(coordinates))
                edges.append(
                    GraphEdge(
                        way.osm_id,
                        segment_index,
                        -1,
                        target_id,
                        source_id,
                        reverse_coordinates,
                        segment_distance,
                        travel_time,
                        way.tags["highway"].lower(),
                        speed,
                        traversal != 0,
                        way_metadata,
                    )
                )
    graph_nodes = tuple(
        GraphNode(node_id, (nodes[node_id].longitude, nodes[node_id].latitude), {})
        for node_id in sorted(retained_node_ids)
    )
    graph_edges = tuple(edges)
    stats.directed_edges = len(graph_edges)
    stats.total_distance_m = sum(edge.distance_m for edge in graph_edges)
    _connectivity(graph_nodes, graph_edges, stats)
    if not graph_nodes or not graph_edges:
        raise ValueError("OSM source produced no valid drivable graph segments")
    return ImportGraph(graph_nodes, graph_edges, _boundary(list(graph_nodes)), stats)

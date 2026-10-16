from math import isfinite

from .models import ImportGraph


def validate_graph(graph: ImportGraph) -> None:
    node_coords = {node.osm_id: node.coordinate for node in graph.nodes}
    if len(node_coords) != len(graph.nodes):
        raise ValueError("graph contains duplicate OSM node IDs")
    for edge in graph.edges:
        source_coord = node_coords.get(edge.source_osm_node_id)
        target_coord = node_coords.get(edge.target_osm_node_id)
        if source_coord is None or target_coord is None:
            raise ValueError(
                f"edge {edge.osm_way_id}:{edge.segment_index} references a missing node"
            )
        if edge.source_osm_node_id == edge.target_osm_node_id:
            raise ValueError("graph contains a prohibited self-loop")
        if len(edge.coordinates) < 2 or edge.coordinates[0] != source_coord:
            raise ValueError("edge geometry does not start at its source node")
        if edge.coordinates[-1] != target_coord:
            raise ValueError("edge geometry does not end at its target node")
        if not isfinite(edge.distance_m) or edge.distance_m <= 0:
            raise ValueError("edge distance must be positive and finite")
        if not isfinite(edge.base_travel_time_s) or edge.base_travel_time_s <= 0:
            raise ValueError("edge travel time must be positive and finite")
        if not isfinite(edge.speed_limit_kph) or edge.speed_limit_kph <= 0:
            raise ValueError("edge speed must be positive and finite")

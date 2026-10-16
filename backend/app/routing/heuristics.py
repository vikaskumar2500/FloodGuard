from math import asin, cos, radians, sin, sqrt
from uuid import UUID

from .models import RoutingGraph

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(first: tuple[float, float], second: tuple[float, float]) -> float:
    first_lon, first_lat = map(radians, first)
    second_lon, second_lat = map(radians, second)
    delta_lat = second_lat - first_lat
    delta_lon = second_lon - first_lon
    value = sin(delta_lat / 2) ** 2 + cos(first_lat) * cos(second_lat) * sin(delta_lon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(value))


def travel_time_heuristic(graph: RoutingGraph, node_id: UUID, goal_id: UUID) -> float:
    """Lower-bound remaining seconds using the fastest edge speed in the graph."""
    if node_id == goal_id:
        return 0.0
    return (
        haversine_m(graph.nodes[node_id].coordinate, graph.nodes[goal_id].coordinate)
        / graph.max_speed_mps
    )

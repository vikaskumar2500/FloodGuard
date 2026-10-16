from dataclasses import dataclass, field
from math import isfinite
from uuid import UUID

Coordinate = tuple[float, float]


@dataclass(frozen=True)
class RoutingNode:
    id: UUID
    coordinate: Coordinate


@dataclass(frozen=True)
class RoutingEdge:
    id: UUID
    source: UUID
    target: UUID
    distance_m: float
    base_travel_time_s: float
    geometry: tuple[Coordinate, ...]
    speed_limit_mps: float | None = None


@dataclass
class RoutingGraph:
    nodes: dict[UUID, RoutingNode] = field(default_factory=dict)
    edges: dict[UUID, RoutingEdge] = field(default_factory=dict)
    adjacency: dict[UUID, list[RoutingEdge]] = field(default_factory=dict)
    max_speed_mps: float = 0.0

    def add_node(self, node: RoutingNode) -> None:
        if not all(isfinite(value) for value in node.coordinate):
            raise ValueError("routing node coordinates must be finite")
        self.nodes[node.id] = node
        self.adjacency.setdefault(node.id, [])

    def add_edge(self, edge: RoutingEdge) -> None:
        if edge.source not in self.nodes or edge.target not in self.nodes:
            raise ValueError("routing edge references a missing node")
        if edge.source == edge.target:
            raise ValueError("routing graph cannot contain self-loops")
        if not isfinite(edge.base_travel_time_s) or edge.base_travel_time_s < 0:
            raise ValueError("routing edge travel time must be finite and nonnegative")
        if not isfinite(edge.distance_m) or edge.distance_m < 0:
            raise ValueError("routing edge distance must be finite and nonnegative")
        if edge.speed_limit_mps is not None and (
            not isfinite(edge.speed_limit_mps) or edge.speed_limit_mps <= 0
        ):
            raise ValueError("routing edge speed limit must be positive and finite")
        if len(edge.geometry) < 2:
            raise ValueError("routing edge geometry requires at least two coordinates")
        if edge.geometry[0] != self.nodes[edge.source].coordinate:
            raise ValueError("routing edge geometry is not source-oriented")
        if edge.geometry[-1] != self.nodes[edge.target].coordinate:
            raise ValueError("routing edge geometry is not target-oriented")
        self.edges[edge.id] = edge
        self.adjacency.setdefault(edge.source, []).append(edge)
        if edge.distance_m > 0 and edge.base_travel_time_s > 0:
            effective_speed = edge.distance_m / edge.base_travel_time_s
            self.max_speed_mps = max(self.max_speed_mps, effective_speed)

    def validate(self) -> None:
        if not self.nodes:
            raise ValueError("routing graph is empty")
        for edge in self.edges.values():
            if edge.source not in self.nodes or edge.target not in self.nodes:
                raise ValueError("routing graph has a dangling edge")
        if self.max_speed_mps <= 0:
            raise ValueError("routing graph has no positive-speed edges")


@dataclass(frozen=True)
class PathResult:
    found: bool
    edge_ids: tuple[UUID, ...]
    node_ids: tuple[UUID, ...]
    total_cost: float
    expanded_nodes: int

    @classmethod
    def not_found(cls, expanded_nodes: int) -> "PathResult":
        return cls(False, (), (), float("inf"), expanded_nodes)


@dataclass(frozen=True)
class RouteGeometry:
    type: str
    coordinates: tuple[Coordinate, ...]


def assemble_geometry(graph: RoutingGraph, edge_ids: tuple[UUID, ...]) -> RouteGeometry:
    coordinates: list[Coordinate] = []
    for edge_id in edge_ids:
        edge = graph.edges[edge_id]
        if not coordinates:
            coordinates.extend(edge.geometry)
        else:
            coordinates.extend(edge.geometry[1:])
    return RouteGeometry("LineString", tuple(coordinates))

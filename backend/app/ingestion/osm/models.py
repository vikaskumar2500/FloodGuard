from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import UUID

Coordinate = tuple[float, float]
Direction = Literal[-1, 1]


@dataclass(frozen=True)
class OSMNode:
    osm_id: int
    longitude: float
    latitude: float


@dataclass(frozen=True)
class OSMWay:
    osm_id: int
    node_ids: tuple[int, ...]
    tags: dict[str, str]


@dataclass(frozen=True)
class GraphNode:
    osm_id: int
    coordinate: Coordinate
    metadata: dict[str, str]


@dataclass(frozen=True)
class GraphEdge:
    osm_way_id: int
    segment_index: int
    direction: Direction
    source_osm_node_id: int
    target_osm_node_id: int
    coordinates: tuple[Coordinate, ...]
    distance_m: float
    base_travel_time_s: float
    road_class: str
    speed_limit_kph: float
    is_one_way: bool
    metadata: dict[str, str]


@dataclass
class GraphStats:
    osm_nodes_read: int = 0
    osm_ways_read: int = 0
    accepted_road_ways: int = 0
    excluded_road_ways: int = 0
    restricted_roads_skipped: int = 0
    invalid_segments_skipped: int = 0
    malformed_speed_tags: int = 0
    one_way_ways: int = 0
    two_way_ways: int = 0
    directed_edges: int = 0
    total_distance_m: float = 0.0
    weakly_connected_components: int = 0
    largest_component_percent: float = 0.0


@dataclass(frozen=True)
class ImportGraph:
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    boundary: tuple[Coordinate, ...]
    stats: GraphStats = field(default_factory=GraphStats)


@dataclass(frozen=True)
class ImportResult:
    region_slug: str
    graph_version: int
    source: str
    source_sha256: str
    graph: ImportGraph
    graph_version_id: UUID


@dataclass(frozen=True)
class OSMInput:
    path: Path
    region_slug: str
    region_name: str
    graph_version: int | None = None

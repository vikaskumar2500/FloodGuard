"""Road topology and static geographic feature computation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoadEdgeAttributes:
    edge_id: str
    road_class: str = "primary"
    length_m: float = 100.0
    speed_limit_mps: float | None = 13.88  # ~50 km/h
    is_bridge: bool = False
    is_tunnel: bool = False
    elevation_m: float | None = None


def compute_road_features(
    road_attr: RoadEdgeAttributes,
    dist_to_flood_zone_m: float | None = None,
) -> dict[str, Any]:
    """Extract road topology and static geographic features for an edge."""
    return {
        "road_class": road_attr.road_class,
        "length_m": round(road_attr.length_m, 2),
        "speed_limit_mps": road_attr.speed_limit_mps,
        "is_bridge": road_attr.is_bridge,
        "is_tunnel": road_attr.is_tunnel,
        "edge_elevation_m": road_attr.elevation_m,
        "dist_to_flood_zone_m": dist_to_flood_zone_m,
    }


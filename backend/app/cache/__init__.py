"""FloodGuard Phase 9 Redis Caching Layer.

Provides structured caching for:
- Routing Graphs (immutable graph_version_id)
- Route Calculations (versioned by risk revision and graph version)
- Risk Snapshots (versioned by risk revision and graph version)

Includes process-local single-flight stampede protection, graceful degradations,
metrics tracking, and key management tools.
"""

from .clear import clear_cache
from .graph_cache import GraphCache
from .inspect import inspect_cache
from .keys import (
    KEY_PREFIX,
    compute_config_hash,
    graph_cache_key,
    risk_cache_key,
    route_cache_key,
)
from .metrics import CacheMetrics
from .risk_cache import RiskSnapshotCache
from .route_cache import RouteCache
from .serializer import (
    deserialize_model,
    dto_to_graph,
    dto_to_risk_snapshot,
    graph_to_dto,
    risk_snapshot_to_dto,
    route_calculation_to_dto,
    serialize_model,
)
from .single_flight import SingleFlight

__all__ = [
    "KEY_PREFIX",
    "CacheMetrics",
    "GraphCache",
    "RiskSnapshotCache",
    "RouteCache",
    "SingleFlight",
    "clear_cache",
    "compute_config_hash",
    "deserialize_model",
    "dto_to_graph",
    "dto_to_risk_snapshot",
    "graph_cache_key",
    "graph_to_dto",
    "inspect_cache",
    "risk_cache_key",
    "risk_snapshot_to_dto",
    "route_cache_key",
    "route_calculation_to_dto",
    "serialize_model",
]

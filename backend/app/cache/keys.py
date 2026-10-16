import hashlib
from typing import Any
from uuid import UUID

KEY_PREFIX = "floodguard:v1"


def compute_config_hash(*items: Any) -> str:
    """Compute a short deterministic hex hash representing cost/routing configurations.

    This ensures that changes to routing penalties or expansion limits automatically
    produce cache misses without broad invalidation.
    """
    hasher = hashlib.sha256()
    for item in items:
        hasher.update(str(item).encode("utf-8"))
        hasher.update(b"|")
    return hasher.hexdigest()[:12]


def graph_cache_key(graph_version_id: UUID | str) -> str:
    """Generate cache key for immutable graph topology."""
    return f"{KEY_PREFIX}:graph:{graph_version_id}"


def route_cache_key(
    graph_version_id: UUID | str,
    source_node_id: UUID | str,
    destination_node_id: UUID | str,
    mode: str,
    algorithm: str,
    risk_revision: int,
    config_hash: str,
) -> str:
    """Generate cache key for route calculations.

    Includes risk_revision so any environmental state advancement invalidates
    the cache key automatically with zero scan overhead.
    """
    return (
        f"{KEY_PREFIX}:route:{graph_version_id}:{source_node_id}:{destination_node_id}:"
        f"{mode.upper()}:{algorithm.upper()}:{risk_revision}:{config_hash}"
    )


def risk_cache_key(
    graph_version_id: UUID | str,
    risk_revision: int,
    config_hash: str,
) -> str:
    """Generate cache key for deterministic risk evaluations."""
    return f"{KEY_PREFIX}:risk:{graph_version_id}:{risk_revision}:{config_hash}"


def ml_prediction_cache_key(
    graph_version_id: UUID | str,
    model_version: str,
    risk_revision: int,
    edge_id: UUID | str,
    config_hash: str,
) -> str:
    """Generate cache key for edge-level ML flood predictions.

    Incorporates model_version and risk_revision to guarantee that model rollbacks,
    updates, or environmental changes naturally invalidate predictions without scans.
    """
    return (
        f"{KEY_PREFIX}:ml-prediction:{graph_version_id}:{model_version}:"
        f"{risk_revision}:{edge_id}:{config_hash}"
    )


def idempotency_key(event_id: str) -> str:
    """Generate cache key for event idempotency deduplication."""
    return f"{KEY_PREFIX}:idempotency:{event_id}"

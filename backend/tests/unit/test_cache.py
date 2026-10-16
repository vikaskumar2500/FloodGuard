import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.cache.clear import clear_cache
from app.cache.graph_cache import GraphCache
from app.cache.inspect import inspect_cache
from app.cache.keys import (
    compute_config_hash,
    graph_cache_key,
    risk_cache_key,
    route_cache_key,
)
from app.cache.metrics import CacheMetrics
from app.cache.models import CachedGraphDTO
from app.cache.risk_cache import RiskSnapshotCache
from app.cache.route_cache import RouteCache
from app.cache.serializer import (
    deserialize_model,
    dto_to_graph,
    dto_to_risk_snapshot,
    graph_to_dto,
    risk_snapshot_to_dto,
    route_calculation_to_dto,
    serialize_model,
)
from app.cache.single_flight import SingleFlight
from app.risk.models import EdgeRiskAssessment, RiskSnapshot
from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode
from app.routing.service import RouteCalculation


class InMemoryFakeRedis:
    def __init__(self) -> None:
        self.storage: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.error_on_get = False
        self.error_on_set = False

    async def get(self, key: str) -> str | None:
        if self.error_on_get:
            raise RedisConnectionError("Fake connection failure")
        return self.storage.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        if self.error_on_set:
            raise RedisConnectionError("Fake connection failure")
        self.storage[key] = value
        if ex:
            self.ttls[key] = ex
        return True

    async def ping(self) -> bool:
        if self.error_on_get:
            raise RedisConnectionError("Fake connection failure")
        return True

    async def aclose(self) -> None:
        pass

    async def ttl(self, key: str) -> int:
        return self.ttls.get(key, -1)

    async def type(self, key: str) -> str:
        return "string" if key in self.storage else "none"

    async def memory_usage(self, key: str) -> int:
        return len(self.storage.get(key, "").encode("utf-8"))

    async def scan_iter(self, match: str = "*", count: int = 10):
        import fnmatch

        for k in list(self.storage.keys()):
            if fnmatch.fnmatch(k, match):
                yield k

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self.storage:
                del self.storage[k]
                self.ttls.pop(k, None)
                deleted += 1
        return deleted


def make_test_graph() -> tuple[UUID, RoutingGraph]:
    version_id = uuid4()
    graph = RoutingGraph()
    n1 = uuid4()
    n2 = uuid4()
    graph.add_node(RoutingNode(n1, (72.8, 19.0)))
    graph.add_node(RoutingNode(n2, (72.81, 19.01)))
    edge_id = uuid4()
    graph.add_edge(
        RoutingEdge(
            edge_id,
            n1,
            n2,
            distance_m=150.0,
            base_travel_time_s=18.0,
            geometry=((72.8, 19.0), (72.81, 19.01)),
            speed_limit_mps=10.0,
        )
    )
    graph.validate()
    return version_id, graph


def make_test_risk(graph_version_id: UUID, edge_id: UUID) -> RiskSnapshot:
    assessments = {
        edge_id: EdgeRiskAssessment(
            edge_id=edge_id,
            risk_score=0.45,
            risk_level="MODERATE",
            confidence=0.8,
            flood_zone_score=0.5,
            water_depth_score=0.4,
            rainfall_score=0.2,
            prediction_score=0.0,
            incident_score=0.0,
            evidence_age_seconds=12.0,
            explanation="Moderate flood risk on segment",
            high_risk_distance_m=0.0,
        )
    }
    return RiskSnapshot(datetime.now(UTC), "deterministic-v1", assessments)


# ==========================================
# 1. Key Formatting & Hashing
# ==========================================


def test_cache_keys_are_canonical_and_namespaced():
    version_id = uuid4()
    src = uuid4()
    dest = uuid4()
    config_hash = compute_config_hash(120.0, 900.0, 60.0)

    g_key = graph_cache_key(version_id)
    assert g_key == f"floodguard:v1:graph:{version_id}"

    r_key = route_cache_key(version_id, src, dest, "SAFEST", "ASTAR", 3, config_hash)
    assert r_key == f"floodguard:v1:route:{version_id}:{src}:{dest}:SAFEST:ASTAR:3:{config_hash}"

    risk_k = risk_cache_key(version_id, 3, config_hash)
    assert risk_k == f"floodguard:v1:risk:{version_id}:3:{config_hash}"


def test_config_hash_changes_deterministically():
    hash1 = compute_config_hash(120.0, 900.0)
    hash2 = compute_config_hash(120.0, 900.0)
    hash3 = compute_config_hash(150.0, 900.0)

    assert hash1 == hash2
    assert hash1 != hash3


# ==========================================
# 2. Serialization & Corruption Resilience
# ==========================================


def test_graph_serialization_round_trip():
    version_id, graph = make_test_graph()
    dto = graph_to_dto(version_id, graph)
    serialized = serialize_model(dto)
    deserialized_dto = deserialize_model(serialized, CachedGraphDTO)
    assert deserialized_dto is not None

    reconstructed_graph = dto_to_graph(deserialized_dto)
    assert len(reconstructed_graph.nodes) == len(graph.nodes)
    assert len(reconstructed_graph.edges) == len(graph.edges)
    edge_id = next(iter(graph.edges.keys()))
    assert reconstructed_graph.edges[edge_id].distance_m == 150.0
    assert reconstructed_graph.edges[edge_id].base_travel_time_s == 18.0


def test_risk_snapshot_serialization_round_trip():
    version_id, graph = make_test_graph()
    edge_id = next(iter(graph.edges.keys()))
    snapshot = make_test_risk(version_id, edge_id)

    dto = risk_snapshot_to_dto(version_id, 2, snapshot)
    serialized = serialize_model(dto)
    from app.cache.models import CachedRiskSnapshotDTO

    deserialized_dto = deserialize_model(serialized, CachedRiskSnapshotDTO)
    assert deserialized_dto is not None

    reconstructed_snapshot = dto_to_risk_snapshot(deserialized_dto)
    assessment = reconstructed_snapshot.for_edge(edge_id)
    assert assessment.risk_score == 0.45
    assert assessment.risk_level == "MODERATE"
    assert assessment.water_depth_score == 0.4


def test_deserialization_corruption_safety():
    # Corrupt string / bad json
    bad_data = "{not a valid json"
    result = deserialize_model(bad_data, CachedGraphDTO)
    assert result is None

    # Schema mismatch
    schema_mismatch = '{"version_id": "123", "unknown_field": 42}'
    result = deserialize_model(schema_mismatch, CachedGraphDTO)
    assert result is None


# ==========================================
# 3. Metrics Tracking
# ==========================================


def test_cache_metrics_records_hits_misses_and_ratios():
    metrics = CacheMetrics()
    metrics.record_hit("graph")
    metrics.record_hit("graph")
    metrics.record_miss("graph")
    metrics.record_set("graph")

    metrics.record_hit("route")
    metrics.record_miss("route")

    snapshot = metrics.snapshot()
    assert snapshot["domains"]["graph"]["hits"] == 2
    assert snapshot["domains"]["graph"]["misses"] == 1
    assert snapshot["domains"]["graph"]["sets"] == 1
    assert snapshot["domains"]["graph"]["hit_ratio"] == 0.6667

    assert snapshot["domains"]["route"]["hits"] == 1
    assert snapshot["domains"]["route"]["misses"] == 1
    assert snapshot["domains"]["route"]["hit_ratio"] == 0.5

    assert snapshot["overall"]["hits"] == 3
    assert snapshot["overall"]["misses"] == 2
    assert snapshot["overall"]["hit_ratio"] == 0.6

    metrics.reset()
    assert metrics.snapshot()["overall"]["hits"] == 0


# ==========================================
# 4. SingleFlight Stampede Protection
# ==========================================


@pytest.mark.asyncio
async def test_single_flight_coalesces_concurrent_calls():
    sf = SingleFlight()
    execution_count = 0

    async def expensive_calc():
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.05)
        return "result-value"

    tasks = [sf.execute("test-key", expensive_calc) for _ in range(10)]
    results = await asyncio.gather(*tasks)

    assert execution_count == 1
    assert all(r == "result-value" for r in results)


@pytest.mark.asyncio
async def test_single_flight_propagates_exceptions():
    sf = SingleFlight()

    async def failing_calc():
        await asyncio.sleep(0.01)
        raise ValueError("calc-failure")

    with pytest.raises(ValueError, match="calc-failure"):
        await sf.execute("err-key", failing_calc)


# ==========================================
# 5. GraphCache, RiskCache, RouteCache with Fallback
# ==========================================


@pytest.mark.asyncio
async def test_graph_cache_crud_and_max_bytes_guard():
    redis = InMemoryFakeRedis()
    metrics = CacheMetrics()
    # Cache with 100 bytes max (will reject graph larger than 100 bytes)
    restricted_cache = GraphCache(redis, max_bytes=100, metrics=metrics)
    version_id, graph = make_test_graph()

    # Set should fail because serialized graph > 100 bytes
    success = await restricted_cache.set(version_id, graph)
    assert success is False
    assert (await restricted_cache.get(version_id)) is None

    # Normal cache
    normal_cache = GraphCache(redis, max_bytes=10_000, metrics=metrics)
    assert await normal_cache.set(version_id, graph) is True
    cached_graph = await normal_cache.get(version_id)
    assert cached_graph is not None
    assert len(cached_graph.nodes) == len(graph.nodes)
    assert metrics.snapshot()["domains"]["graph"]["hits"] == 1


@pytest.mark.asyncio
async def test_cache_graceful_degradation_on_redis_error():
    redis = InMemoryFakeRedis()
    redis.error_on_get = True
    redis.error_on_set = True

    metrics = CacheMetrics()
    graph_cache = GraphCache(redis, metrics=metrics)
    version_id, graph = make_test_graph()

    # Never raises; safely returns None or False
    assert await graph_cache.get(version_id) is None
    assert await graph_cache.set(version_id, graph) is False
    assert metrics.snapshot()["domains"]["graph"]["errors"] == 2


@pytest.mark.asyncio
async def test_risk_cache_crud_and_invalidation():
    redis = InMemoryFakeRedis()
    metrics = CacheMetrics()
    risk_cache = RiskSnapshotCache(redis, metrics=metrics)

    version_id, graph = make_test_graph()
    edge_id = next(iter(graph.edges.keys()))
    snapshot = make_test_risk(version_id, edge_id)
    config_hash = "conf-v1"

    # Miss at revision 0
    assert await risk_cache.get(version_id, 0, config_hash) is None

    # Set at revision 0
    assert await risk_cache.set(version_id, 0, config_hash, snapshot) is True

    # Hit at revision 0
    cached = await risk_cache.get(version_id, 0, config_hash)
    assert cached is not None
    assert cached.for_edge(edge_id).risk_score == 0.45

    # Automatic invalidation at revision 1
    assert await risk_cache.get(version_id, 1, config_hash) is None


# ==========================================
# 6. Route Invalidation & Key Change Tests
# ==========================================


@pytest.mark.asyncio
async def test_route_cache_automatic_invalidation_on_revision_advance():
    redis = InMemoryFakeRedis()
    metrics = CacheMetrics()
    route_cache = RouteCache(redis, metrics=metrics)

    graph_version_id = uuid4()
    src = uuid4()
    dest = uuid4()
    config_hash = "conf-1"

    calc = RouteCalculation(
        route_id=uuid4(),
        graph_version_id=graph_version_id,
        algorithm="ASTAR",
        mode="SAFEST",
        distance_m=500.0,
        estimated_time_s=60.0,
        risk_score=0.1,
        risk_level="LOW",
        risk_confidence=0.9,
        max_edge_risk=0.15,
        high_risk_distance_m=0.0,
        risk_segments=(),
        risk_model_active=True,
        expanded_nodes=5,
        geometry_type="LineString",
        geometry_coordinates=((0.0, 0.0), (0.001, 0.001)),
    )
    template = route_calculation_to_dto(calc, src, dest, risk_revision=0)

    # Set route at revision 0
    await route_cache.set(graph_version_id, src, dest, "SAFEST", "ASTAR", 0, config_hash, template)

    # HIT at revision 0
    hit = await route_cache.get(graph_version_id, src, dest, "SAFEST", "ASTAR", 0, config_hash)
    assert hit is not None
    assert hit.risk_score == 0.1

    # MISS at revision 1 (environmental change occurred)
    miss_rev1 = await route_cache.get(
        graph_version_id, src, dest, "SAFEST", "ASTAR", 1, config_hash
    )
    assert miss_rev1 is None


# ==========================================
# 7. Safe Inspect and Clear Tools
# ==========================================


@pytest.mark.asyncio
async def test_inspect_and_clear_utilities():
    redis = InMemoryFakeRedis()
    await redis.set("floodguard:v1:graph:g1", "data-1", ex=3600)
    await redis.set("floodguard:v1:route:r1", "data-2", ex=1800)
    await redis.set("floodguard:v1:risk:k1", "data-3", ex=900)
    await redis.set("other:unrelated", "data-4")

    report = await inspect_cache(redis)
    assert report["total_keys"] == 3
    assert report["summary"]["graph"] == 1
    assert report["summary"]["route"] == 1
    assert report["summary"]["risk"] == 1

    cleared = await clear_cache(redis, pattern="floodguard:v1:*")
    assert cleared["deleted_count"] == 3
    assert len(redis.storage) == 1
    assert "other:unrelated" in redis.storage

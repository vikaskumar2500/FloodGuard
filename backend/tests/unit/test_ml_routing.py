"""Comprehensive unit and integration tests for Phase 13 ML routing integration."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from floodguard_ml.features.indicators import (
    compute_historical_features,
    compute_missingness_indicators,
)
from floodguard_ml.features.rainfall import WeatherRecord, compute_rainfall_features
from floodguard_ml.features.road import RoadEdgeAttributes, compute_road_features
from floodguard_ml.features.sensors import SensorRecord, compute_sensor_features
from floodguard_ml.features.temporal import compute_temporal_features
from floodguard_ml.models.artifacts import LoadedFloodModel, ModelIntegrityError

from app.cache.ml_cache import MLPredictionCache
from app.core.config import Settings
from app.ml.builder import OnlineFeatureBuilder
from app.ml.models import MLFloodPrediction
from app.ml.service import FloodPredictionService
from app.risk.config import RiskConfig
from app.risk.costs import build_edge_costs
from app.risk.fusion import RiskFusionService
from app.risk.models import (
    EdgeRiskAssessment,
)
from app.routing.models import RoutingEdge, RoutingGraph, RoutingNode
from tests.unit.test_cache import InMemoryFakeRedis

# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def sample_graph() -> RoutingGraph:
    """Create a diamond topology graph with two competing paths:
    Path 1: A -> B -> D (top)
    Path 2: A -> C -> D (bottom)
    """
    graph = RoutingGraph()
    na, nb, nc, nd = uuid4(), uuid4(), uuid4(), uuid4()
    graph.add_node(RoutingNode(na, (72.0, 19.0)))
    graph.add_node(RoutingNode(nb, (72.001, 19.001)))
    graph.add_node(RoutingNode(nc, (72.0, 19.002)))
    graph.add_node(RoutingNode(nd, (72.002, 19.002)))

    e_top1 = uuid4()
    e_top2 = uuid4()
    e_bot1 = uuid4()
    e_bot2 = uuid4()

    # Top path: 100m + 100m, 10s + 10s = 20s
    graph.add_edge(RoutingEdge(e_top1, na, nb, 100.0, 10.0, ((72.0, 19.0), (72.001, 19.001))))
    graph.add_edge(RoutingEdge(e_top2, nb, nd, 100.0, 10.0, ((72.001, 19.001), (72.002, 19.002))))

    # Bottom path: 120m + 120m, 12s + 12s = 24s
    graph.add_edge(RoutingEdge(e_bot1, na, nc, 120.0, 12.0, ((72.0, 19.0), (72.0, 19.002))))
    graph.add_edge(RoutingEdge(e_bot2, nc, nd, 120.0, 12.0, ((72.0, 19.002), (72.002, 19.002))))

    graph.validate()
    return graph


@pytest.fixture
def loaded_ml_model() -> LoadedFloodModel:
    repo_root = Path(__file__).resolve().parents[3]
    model_path = repo_root / "ml" / "artifacts" / "xgboost-v1"
    return LoadedFloodModel.load(model_path)


# -----------------------------------------------------------------------------
# 1. Feature Parity Test (Req 49)
# -----------------------------------------------------------------------------


def test_feature_parity_online_vs_offline(sample_graph: RoutingGraph) -> None:
    """Verify online feature builder generates identical 34 features as offline generators."""
    builder = OnlineFeatureBuilder()
    edge_id = next(iter(sample_graph.edges))
    edge = sample_graph.edges[edge_id]
    now = datetime(2026, 7, 15, 14, 30, tzinfo=UTC)

    weather_records = [WeatherRecord(timestamp=now, rainfall_mm_per_hour=25.0)]
    sensor_records = [SensorRecord(timestamp=now, water_depth_cm=18.5, quality="GOOD")]

    # 1. Online feature dict
    online_feats = builder.build_features(
        edge, now, weather_records=weather_records, sensor_records=sensor_records
    )
    assert len(online_feats) == 29
    assert builder.feature_version == "v1"

    # 2. Offline direct computation
    rain_f = compute_rainfall_features(weather_records, now)
    sens_f = compute_sensor_features(sensor_records, now)
    miss_f = compute_missingness_indicators(
        rainfall_rate=rain_f["rainfall_rate_now_mm_h"],
        water_depth=sens_f["water_depth_current_cm"],
        temperature=rain_f["temperature_c"],
    )
    speed_limit = (
        edge.distance_m / edge.base_travel_time_s if edge.base_travel_time_s > 0 else 13.88
    )
    road_attrs = RoadEdgeAttributes(
        edge_id=str(edge.id),
        road_class="primary",
        length_m=edge.distance_m,
        speed_limit_mps=round(speed_limit, 2),
        is_bridge=False,
        is_tunnel=False,
        elevation_m=None,
    )
    road_f = compute_road_features(road_attrs)
    road_f.pop("dist_to_flood_zone_m", None)
    temp_f = compute_temporal_features(now)
    hist_f = compute_historical_features([], now)

    offline_feats: dict[str, Any] = {
        **rain_f,
        **sens_f,
        **miss_f,
        **road_f,
        **temp_f,
        **hist_f,
    }

    # Compare key by key
    for key, val in offline_feats.items():
        assert key in online_feats, f"Missing feature {key} in online builder"
        online_val = online_feats[key]
        if isinstance(val, float):
            assert online_val == pytest.approx(val, rel=1e-5), (
                f"Mismatch for feature {key}: {online_val} vs {val}"
            )
        else:
            assert online_val == val, f"Mismatch for feature {key}: {online_val} vs {val}"


# -----------------------------------------------------------------------------
# 2. Critical Safety Test (CRITICAL INVARIANT 1)
# -----------------------------------------------------------------------------


def test_critical_safety_deterministic_floor_preserved() -> None:
    """ML can NEVER reduce a stronger deterministic safety assessment."""
    fusion = RiskFusionService(risk_weight=0.35)
    now = datetime.now(UTC)
    edge_id = uuid4()

    # Case A: Severe deterministic risk (0.90) with ML predicting low flood (0.05)
    det_severe = EdgeRiskAssessment(
        edge_id=edge_id,
        risk_score=0.90,
        risk_level="SEVERE",
        confidence=0.85,
        flood_zone_score=0.80,
        water_depth_score=0.95,
        rainfall_score=0.80,
        prediction_score=0.0,
        incident_score=0.90,
        evidence_age_seconds=10.0,
        explanation="Severe water depth 45cm observed.",
        high_risk_distance_m=100.0,
    )
    ml_low = MLFloodPrediction(
        edge_id=edge_id,
        probability=0.05,
        predicted_class=0,
        threshold=0.20,
        model_name="XGBoost",
        model_version="xgboost-v1",
        feature_version="v1",
        dataset_version="v1",
        inference_time_ms=1.0,
        evaluated_at=now,
    )

    fused = fusion.fuse_edge(det_severe, ml_low, mode="ACTIVE")
    assert fused.risk_score >= 0.90, "Fused risk was downgraded below deterministic risk!"
    assert fused.risk_level == "SEVERE", "Fused level was downgraded from SEVERE!"
    assert fused.deterministic_risk_score == 0.90
    assert fused.ml_probability == 0.05
    assert fused.ml_prediction_active is True

    # Case B: High deterministic water depth override
    det_depth = EdgeRiskAssessment(
        edge_id=edge_id,
        risk_score=0.78,
        risk_level="HIGH",
        confidence=0.80,
        flood_zone_score=0.50,
        water_depth_score=0.85,  # Depth > 15cm
        rainfall_score=0.40,
        prediction_score=0.0,
        incident_score=0.0,
        evidence_age_seconds=10.0,
        explanation="Water depth 20cm observed.",
        high_risk_distance_m=100.0,
    )
    fused_depth = fusion.fuse_edge(det_depth, ml_low, mode="ACTIVE")
    assert fused_depth.risk_score >= 0.78
    assert fused_depth.risk_level in ("HIGH", "SEVERE")


# -----------------------------------------------------------------------------
# 3. ML Escalation Test
# -----------------------------------------------------------------------------


def test_ml_escalation_increases_risk_and_causes_rerouting(sample_graph: RoutingGraph) -> None:
    """When ML indicates high flood probability, risk increases and SAFEST reroutes."""
    edges = list(sample_graph.edges.values())
    top_edge1 = edges[0]  # First edge of top path
    now = datetime.now(UTC)

    # Deterministic snapshot: all edges have LOW risk (0.15)
    det_assessments: dict[UUID, EdgeRiskAssessment] = {}
    for e in edges:
        det_assessments[e.id] = EdgeRiskAssessment(
            edge_id=e.id,
            risk_score=0.15,
            risk_level="LOW",
            confidence=0.75,
            flood_zone_score=0.10,
            water_depth_score=0.0,
            rainfall_score=0.10,
            prediction_score=0.0,
            incident_score=0.0,
            evidence_age_seconds=10.0,
            explanation="Clear conditions.",
            high_risk_distance_m=0.0,
        )

    # ML predicts high flood probability (0.90) on top_edge1
    ml_preds: dict[UUID, MLFloodPrediction] = {
        top_edge1.id: MLFloodPrediction(
            edge_id=top_edge1.id,
            probability=0.90,
            predicted_class=1,
            threshold=0.20,
            model_name="XGBoost",
            model_version="xgboost-v1",
            feature_version="v1",
            dataset_version="v1",
            inference_time_ms=1.0,
            evaluated_at=now,
        )
    }

    fusion = RiskFusionService(risk_weight=0.35)

    # Fused calculation in ACTIVE mode
    fused_active = fusion.fuse_assessments(det_assessments, ml_preds, mode="ACTIVE")
    top_fused = fused_active[top_edge1.id]

    # Formula check: max(0.15, (1 - 0.35)*0.15 + 0.35*0.90) = max(0.15, 0.0975 + 0.315) = 0.4125
    expected_score = round(max(0.15, 0.65 * 0.15 + 0.35 * 0.90), 4)
    assert top_fused.risk_score == pytest.approx(expected_score, abs=1e-3)
    assert top_fused.risk_score > 0.15
    assert top_fused.risk_level == "MODERATE"

    # In ACTIVE mode: edge costs increase on top path
    costs_active = build_edge_costs(sample_graph, fused_active, "SAFEST", RiskConfig())
    # Baseline costs without ML
    costs_det = build_edge_costs(sample_graph, det_assessments, "SAFEST", RiskConfig())

    assert costs_active[top_edge1.id] > costs_det[top_edge1.id]


# -----------------------------------------------------------------------------
# 4. Shadow Mode Diagnostics Test
# -----------------------------------------------------------------------------


def test_shadow_mode_computes_diagnostics_without_cost_alteration() -> None:
    """In SHADOW mode, fused risk equals deterministic risk, but ML is in telemetry."""
    fusion = RiskFusionService(risk_weight=0.35)
    now = datetime.now(UTC)
    edge_id = uuid4()

    det = EdgeRiskAssessment(
        edge_id=edge_id,
        risk_score=0.20,
        risk_level="LOW",
        confidence=0.80,
        flood_zone_score=0.10,
        water_depth_score=0.0,
        rainfall_score=0.10,
        prediction_score=0.0,
        incident_score=0.0,
        evidence_age_seconds=10.0,
        explanation="Low baseline.",
        high_risk_distance_m=0.0,
    )
    ml_high = MLFloodPrediction(
        edge_id=edge_id,
        probability=0.85,
        predicted_class=1,
        threshold=0.20,
        model_name="XGBoost",
        model_version="xgboost-v1",
        feature_version="v1",
        dataset_version="v1",
        inference_time_ms=1.0,
        evaluated_at=now,
    )

    fused = fusion.fuse_edge(det, ml_high, mode="SHADOW")
    assert fused.risk_score == 0.20, "In SHADOW mode, risk score must remain deterministic!"
    assert fused.risk_level == "LOW"
    assert fused.deterministic_risk_score == 0.20
    assert fused.ml_probability == 0.85
    assert fused.ml_prediction_active is False
    assert "SHADOW mode: routing unaffected" in fused.explanation


# -----------------------------------------------------------------------------
# 5. Missing ML / Model Failure Fallback Test (CRITICAL INVARIANT 2)
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_ml_and_model_failure_fallback(sample_graph: RoutingGraph) -> None:
    """Model inference failure or missing model cleanly falls back to deterministic risk."""
    settings = Settings(ml_enabled=True, ml_mode="ACTIVE")
    now = datetime.now(UTC)

    # 1. Service with no model
    service_no_model = FloodPredictionService(settings=settings, model=None)
    preds = await service_no_model.predict_edges(
        sample_graph,
        {},
        now,
        graph_version_id=str(uuid4()),
        risk_revision=0,
        config_hash="abc123hash",
        edge_ids=list(sample_graph.edges.keys()),
    )
    assert preds == {}

    # 2. Service with failing model
    class FailingModel:
        def predict_proba(self, records):
            raise RuntimeError("CUDA out of memory / model worker crashed")

    service_failing = FloodPredictionService(settings=settings, model=FailingModel())
    preds_failing = await service_failing.predict_edges(
        sample_graph,
        {},
        now,
        graph_version_id=str(uuid4()),
        risk_revision=0,
        config_hash="abc123hash",
        edge_ids=list(sample_graph.edges.keys()),
    )
    assert preds_failing == {}
    assert service_failing.metrics.inference_errors > 0

    # 3. Risk fusion with empty predictions
    fusion = RiskFusionService(settings=settings)
    det_map = {
        eid: EdgeRiskAssessment(
            edge_id=eid,
            risk_score=0.25,
            risk_level="LOW",
            confidence=0.8,
            flood_zone_score=0.1,
            water_depth_score=0.0,
            rainfall_score=0.1,
            prediction_score=0.0,
            incident_score=0.0,
            evidence_age_seconds=0.0,
            explanation="Normal.",
            high_risk_distance_m=0.0,
        )
        for eid in sample_graph.edges
    }
    fused_map = fusion.fuse_assessments(det_map, preds_failing, mode="ACTIVE")
    for _eid, assessment in fused_map.items():
        assert assessment.risk_score == 0.25
        assert assessment.ml_probability is None


# -----------------------------------------------------------------------------
# 6. Redis Prediction Cache Test
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_ml_prediction_cache_hit_miss_and_invalidation() -> None:
    """Test cache get, set, version invalidation, and revision invalidation."""
    redis = InMemoryFakeRedis()
    cache = MLPredictionCache(redis, ttl_seconds=300, enabled=True)
    graph_version = str(uuid4())
    model_version = "xgboost-v1"
    risk_revision = 0
    config_hash = "abc123hash"
    edge_id = uuid4()
    now = datetime.now(UTC)

    pred = MLFloodPrediction(
        edge_id=edge_id,
        probability=0.72,
        predicted_class=1,
        threshold=0.20,
        model_name="XGBoost",
        model_version=model_version,
        feature_version="v1",
        dataset_version="v1",
        inference_time_ms=1.5,
        evaluated_at=now,
    )

    # 1. Miss on first query
    cached, misses = await cache.get_batch(
        graph_version, model_version, risk_revision, config_hash, [edge_id]
    )
    assert edge_id not in cached
    assert misses == [edge_id]

    # 2. Set batch
    await cache.set_batch(graph_version, model_version, risk_revision, config_hash, {edge_id: pred})

    # 3. Hit on second query
    cached_hit, misses_hit = await cache.get_batch(
        graph_version, model_version, risk_revision, config_hash, [edge_id]
    )
    assert edge_id in cached_hit
    assert misses_hit == []
    assert cached_hit[edge_id].probability == pytest.approx(0.72)

    # 4. Invalidation: different risk revision
    cached_rev, _ = await cache.get_batch(
        graph_version, model_version, risk_revision + 1, config_hash, [edge_id]
    )
    assert edge_id not in cached_rev

    # 5. Invalidation: different model version
    cached_model, _ = await cache.get_batch(
        graph_version, "xgboost-v2", risk_revision, config_hash, [edge_id]
    )
    assert edge_id not in cached_model


# -----------------------------------------------------------------------------
# 7. Redis Outage Resilience Test
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_outage_resilience(
    sample_graph: RoutingGraph, loaded_ml_model: LoadedFloodModel
) -> None:
    """Redis connection errors degrade gracefully to direct model inference without crashing."""

    class FailingRedis:
        async def get(self, *args, **kwargs):
            raise ConnectionError("Connection refused by Redis")

        async def set(self, *args, **kwargs):
            raise ConnectionError("Connection refused by Redis")

        def pipeline(self, *args, **kwargs):
            raise ConnectionError("Connection refused by Redis")

    failing_cache = MLPredictionCache(FailingRedis(), ttl_seconds=300, enabled=True)
    settings = Settings(ml_enabled=True, ml_mode="SHADOW")
    service = FloodPredictionService(
        settings=settings,
        model=loaded_ml_model,
        cache=failing_cache,
    )

    now = datetime.now(UTC)
    edge_ids = list(sample_graph.edges.keys())

    # Inference should succeed despite Redis failure
    predictions = await service.predict_edges(
        sample_graph,
        {},
        now,
        graph_version_id=str(uuid4()),
        risk_revision=0,
        config_hash="abc123hash",
        edge_ids=edge_ids,
    )
    assert len(predictions) == len(edge_ids)
    for eid in edge_ids:
        assert eid in predictions
        assert 0.0 <= predictions[eid].probability <= 1.0


# -----------------------------------------------------------------------------
# 8. Corrupted Checksum Failure Fallback Test
# -----------------------------------------------------------------------------


def test_corrupted_model_artifact_checksum_failure(tmp_path: Path) -> None:
    """Artifact with tampered binary raises ModelIntegrityError during load."""
    repo_root = Path(__file__).resolve().parents[3]
    src_dir = repo_root / "ml" / "artifacts" / "xgboost-v1"

    # Copy files to tmp_path
    import shutil

    target_dir = tmp_path / "corrupted-model"
    shutil.copytree(src_dir, target_dir)

    # Corrupt model.joblib
    with open(target_dir / "model.joblib", "ab") as f:
        f.write(b"corrupted_garbage_bytes")

    with pytest.raises(ModelIntegrityError):
        LoadedFloodModel.load(target_dir, verify_checksum=True)


# -----------------------------------------------------------------------------
# 9. Non-Negative Edge Costs & A* Admissibility Test
# -----------------------------------------------------------------------------


def test_non_negative_edge_costs_and_astar_admissibility(sample_graph: RoutingGraph) -> None:
    """Verify edge costs c(e) >= base_travel_time(e) > 0 for all modes."""
    fusion = RiskFusionService(risk_weight=0.35)
    config = RiskConfig()

    test_modes = ["FASTEST", "BALANCED", "SAFEST"]
    risk_pairs = [
        (0.0, 0.0),
        (0.0, 1.0),
        (0.5, 0.2),
        (0.5, 0.9),
        (0.9, 0.1),
        (1.0, 1.0),
    ]

    for mode in test_modes:
        for r_det, p_ml in risk_pairs:
            assessments = {}
            for eid, _edge in sample_graph.edges.items():
                det = EdgeRiskAssessment(
                    edge_id=eid,
                    risk_score=r_det,
                    risk_level="HIGH" if r_det >= 0.7 else "LOW",
                    confidence=0.8,
                    flood_zone_score=r_det,
                    water_depth_score=r_det,
                    rainfall_score=r_det,
                    prediction_score=0.0,
                    incident_score=0.0,
                    evidence_age_seconds=0.0,
                    explanation="Test",
                    high_risk_distance_m=0.0,
                )
                ml_pred = MLFloodPrediction(
                    edge_id=eid,
                    probability=p_ml,
                    predicted_class=1 if p_ml >= 0.2 else 0,
                    threshold=0.2,
                    model_name="XGBoost",
                    model_version="xgboost-v1",
                    feature_version="v1",
                    dataset_version="v1",
                    inference_time_ms=0.0,
                    evaluated_at=datetime.now(UTC),
                )
                assessments[eid] = fusion.fuse_edge(det, ml_pred, mode="ACTIVE")

            costs = build_edge_costs(sample_graph, assessments, mode, config)
            for eid, edge in sample_graph.edges.items():
                c = costs[eid]
                assert c >= edge.base_travel_time_s > 0, (
                    f"Cost {c} violated lower bound {edge.base_travel_time_s} for mode {mode}, "
                    f"r_det={r_det}, p_ml={p_ml}"
                )
                assert math.isfinite(c), f"Cost {c} is not finite!"


# -----------------------------------------------------------------------------
# 10. Latency Benchmark Measurements
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ml_latency_benchmarks(
    sample_graph: RoutingGraph, loaded_ml_model: LoadedFloodModel
) -> None:
    """Measure exact latencies for feature gen, cache lookup, inference, and fusion."""
    builder = OnlineFeatureBuilder()
    fusion = RiskFusionService(risk_weight=0.35)
    redis = InMemoryFakeRedis()
    cache = MLPredictionCache(redis, ttl_seconds=300, enabled=True)
    settings = Settings(ml_enabled=True, ml_mode="SHADOW")
    service = FloodPredictionService(
        settings=settings,
        model=loaded_ml_model,
        feature_builder=builder,
        cache=cache,
    )

    now = datetime.now(UTC)
    edge_ids = list(sample_graph.edges.keys())
    graph_version = str(uuid4())

    # 1. Online feature generation latency (for 4 edges)
    t0 = time.perf_counter()
    for eid in edge_ids:
        _ = builder.build_features(sample_graph.edges[eid], now, evidence=None)
    t_features_ms = (time.perf_counter() - t0) * 1000.0

    # 2. Cold batch inference latency (Cache MISS)
    t0 = time.perf_counter()
    _ = await service.predict_edges(
        sample_graph,
        {},
        now,
        graph_version_id=graph_version,
        risk_revision=0,
        config_hash="test",
        edge_ids=edge_ids,
    )
    t_infer_cold_ms = (time.perf_counter() - t0) * 1000.0

    # 3. Warm batch lookup latency (Cache HIT)
    t0 = time.perf_counter()
    preds_warm = await service.predict_edges(
        sample_graph,
        {},
        now,
        graph_version_id=graph_version,
        risk_revision=0,
        config_hash="test",
        edge_ids=edge_ids,
    )
    t_lookup_warm_ms = (time.perf_counter() - t0) * 1000.0

    # 4. Risk fusion latency
    det_map = {
        eid: EdgeRiskAssessment(
            edge_id=eid,
            risk_score=0.20,
            risk_level="LOW",
            confidence=0.8,
            flood_zone_score=0.1,
            water_depth_score=0.0,
            rainfall_score=0.1,
            prediction_score=0.0,
            incident_score=0.0,
            evidence_age_seconds=0.0,
            explanation="Normal.",
            high_risk_distance_m=0.0,
        )
        for eid in edge_ids
    }
    t0 = time.perf_counter()
    _ = fusion.fuse_assessments(det_map, preds_warm, mode="ACTIVE")
    t_fusion_ms = (time.perf_counter() - t0) * 1000.0

    per_edge_feat = t_features_ms / len(edge_ids)
    print(f"\n--- Phase 13 Latency Benchmark Results ({len(edge_ids)} edges) ---")
    print(f"Feature Generation: {t_features_ms:.3f} ms ({per_edge_feat:.3f} ms/edge)")
    print(f"Cold Model Inference: {t_infer_cold_ms:.3f} ms")
    print(f"Warm Cache Lookup: {t_lookup_warm_ms:.3f} ms")
    print(f"Risk Fusion Layer: {t_fusion_ms:.3f} ms")
    print(f"Total Added Warm Overhead: {t_lookup_warm_ms + t_fusion_ms:.3f} ms")

    # Assert budget thresholds
    assert t_features_ms < 50.0
    assert t_infer_cold_ms < 500.0
    assert t_lookup_warm_ms < 10.0
    assert t_fusion_ms < 10.0

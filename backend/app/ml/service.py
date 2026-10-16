"""Flood Prediction Service managing batch inference, caching, and diagnostics."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any
from uuid import UUID

from floodguard_ml.models.artifacts import LoadedFloodModel

from app.cache.ml_cache import MLPredictionCache
from app.core.config import Settings
from app.ml.builder import OnlineFeatureBuilder
from app.ml.models import MLFloodPrediction, MLInferenceMetrics, validate_probability
from app.risk.models import EdgeEvidence
from app.routing.models import RoutingGraph

logger = logging.getLogger("floodguard.ml")


class FloodPredictionService:
    """Orchestrates ML feature generation, batch model inference, and cache lookups."""

    def __init__(
        self,
        settings: Settings,
        model: LoadedFloodModel | None = None,
        feature_builder: OnlineFeatureBuilder | None = None,
        cache: MLPredictionCache | None = None,
    ) -> None:
        self.settings = settings
        self.model = model
        self.feature_builder = feature_builder or OnlineFeatureBuilder()
        self.cache = cache
        self.metrics = MLInferenceMetrics()

    @property
    def is_available(self) -> bool:
        return (
            self.model is not None
            and self.settings.ml_enabled
            and self.settings.ml_mode != "DISABLED"
        )

    @property
    def model_version(self) -> str:
        if self.model is not None:
            return str(self.model.metadata.get("model_version", self.settings.ml_model_version))
        return self.settings.ml_model_version

    @property
    def feature_version(self) -> str:
        return self.feature_builder.feature_version

    @property
    def dataset_version(self) -> str:
        if self.model is not None:
            return str(self.model.metadata.get("dataset_version", "unknown"))
        return "unknown"

    @property
    def threshold(self) -> float:
        if self.settings.ml_prediction_threshold is not None:
            return self.settings.ml_prediction_threshold
        if self.model is not None:
            return float(self.model.threshold)
        return 0.20

    async def predict_edges(
        self,
        graph: RoutingGraph,
        evidence_map: dict[UUID, EdgeEvidence],
        now: datetime,
        graph_version_id: UUID | str,
        risk_revision: int,
        config_hash: str,
        edge_ids: list[UUID] | tuple[UUID, ...] | None = None,
    ) -> dict[UUID, MLFloodPrediction]:
        """Generate ML flood predictions for a batch of graph edges.

        Strict contract:
        - Evaluates cache first.
        - Precomputes batch predictions prior to A* search (O(1) relaxation lookup).
        - Degrades safely to empty dictionary on inference error or model absence.
        """
        if not self.is_available:
            return {}

        target_ids = list(edge_ids) if edge_ids is not None else list(graph.edges.keys())
        if not target_ids:
            return {}

        predictions: dict[UUID, MLFloodPrediction] = {}
        missing_ids = target_ids

        # 1. Check Redis Prediction Cache
        if self.cache is not None:
            cached_hits, missing_ids = await self.cache.get_batch(
                graph_version_id=graph_version_id,
                model_version=self.model_version,
                risk_revision=risk_revision,
                config_hash=config_hash,
                edge_ids=target_ids,
            )
            predictions.update(cached_hits)
            for _ in cached_hits:
                self.metrics.record_hit()

        if not missing_ids or self.model is None:
            return predictions

        # 2. Build feature records for missing edges
        records: list[dict[str, Any]] = []
        valid_edge_ids: list[UUID] = []

        for edge_id in missing_ids:
            edge = graph.edges.get(edge_id)
            if edge is None:
                continue
            evidence = evidence_map.get(edge_id)
            try:
                feat_dict = self.feature_builder.build_features(edge, now, evidence=evidence)
                records.append(feat_dict)
                valid_edge_ids.append(edge_id)
            except Exception as err:
                logger.warning("Feature builder error for edge %s: %s", edge_id, err)
                self.metrics.record_schema_error()

        # 3. Execute batch model inference in bounded chunks
        newly_computed: dict[UUID, MLFloodPrediction] = {}
        batch_size = self.settings.ml_max_inference_batch_size
        timeout_s = self.settings.ml_inference_timeout_ms / 1000.0

        for i in range(0, len(records), batch_size):
            chunk_records = records[i : i + batch_size]
            chunk_ids = valid_edge_ids[i : i + batch_size]

            t0_infer = time.perf_counter()
            try:
                # Wrap model predict_proba in asyncio.to_thread with timeout
                proba_array = await asyncio.wait_for(
                    asyncio.to_thread(self.model.predict_proba, chunk_records),
                    timeout=timeout_s,
                )
                t1_infer = time.perf_counter()
                elapsed_ms = (t1_infer - t0_infer) * 1000.0
                per_row_ms = elapsed_ms / len(chunk_records) if chunk_records else 0.0

                for edge_id, prob_row in zip(chunk_ids, proba_array, strict=True):
                    prob = validate_probability(float(prob_row[1]))
                    pred_class = 1 if prob >= self.threshold else 0
                    pred_obj = MLFloodPrediction(
                        edge_id=edge_id,
                        probability=prob,
                        predicted_class=pred_class,
                        threshold=self.threshold,
                        model_name="XGBoost Classifier",
                        model_version=self.model_version,
                        feature_version=self.feature_version,
                        dataset_version=self.dataset_version,
                        inference_time_ms=round(per_row_ms, 3),
                        evaluated_at=now,
                        status="SUCCESS",
                    )
                    newly_computed[edge_id] = pred_obj
                    self.metrics.record_miss(per_row_ms)

                    # Shadow disagreement inspection
                    self._check_shadow_disagreement(edge_id, pred_obj, evidence_map.get(edge_id))

            except TimeoutError:
                logger.error(
                    "ML model inference timed out after %.1f ms",
                    self.settings.ml_inference_timeout_ms,
                )
                self.metrics.record_error()
            except Exception as err:
                logger.error("ML model batch inference failed: %s", err)
                self.metrics.record_error()

        # 4. Cache newly computed predictions in Redis
        if self.cache is not None and newly_computed:
            await self.cache.set_batch(
                graph_version_id=graph_version_id,
                model_version=self.model_version,
                risk_revision=risk_revision,
                config_hash=config_hash,
                predictions=newly_computed,
            )

        predictions.update(newly_computed)
        return predictions

    def _check_shadow_disagreement(
        self,
        edge_id: UUID,
        prediction: MLFloodPrediction,
        evidence: EdgeEvidence | None,
    ) -> None:
        """Log diagnostics when ML prediction diverges strongly from deterministic signals."""
        if self.settings.ml_mode != "SHADOW":
            return

        has_severe_evidence = False
        if evidence:
            for s in evidence.sensors:
                if s.water_depth_cm is not None and s.water_depth_cm >= 15.0:
                    has_severe_evidence = True
            for z in evidence.flood_zones:
                if z.severity in ("HIGH", "SEVERE") or z.score >= 0.75:
                    has_severe_evidence = True

        # Disagreement case A: ML predicts high flood (>= 0.80) while evidence is minimal/dry
        if prediction.probability >= 0.80 and not has_severe_evidence:
            self.metrics.record_shadow_disagreement()
            logger.info(
                "ml_shadow_disagreement",
                extra={
                    "edge_id": str(edge_id),
                    "disagreement_type": "ML_HIGH_DETERMINISTIC_LOW",
                    "ml_probability": prediction.probability,
                    "has_severe_evidence": False,
                },
            )
        # Disagreement case B: ML predicts low flood (<= 0.20) while critical evidence exists
        elif prediction.probability <= 0.20 and has_severe_evidence:
            self.metrics.record_shadow_disagreement()
            logger.info(
                "ml_shadow_disagreement",
                extra={
                    "edge_id": str(edge_id),
                    "disagreement_type": "ML_LOW_DETERMINISTIC_HIGH",
                    "ml_probability": prediction.probability,
                    "has_severe_evidence": True,
                },
            )

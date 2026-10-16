"""Redis cache manager for ML flood predictions."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from redis.asyncio import Redis

from app.cache.keys import ml_prediction_cache_key
from app.cache.metrics import CacheMetrics
from app.ml.models import MLFloodPrediction

logger = logging.getLogger("floodguard.cache.ml")


def _prediction_to_dict(pred: MLFloodPrediction) -> dict[str, Any]:
    return {
        "edge_id": str(pred.edge_id),
        "probability": pred.probability,
        "predicted_class": pred.predicted_class,
        "threshold": pred.threshold,
        "model_name": pred.model_name,
        "model_version": pred.model_version,
        "feature_version": pred.feature_version,
        "dataset_version": pred.dataset_version,
        "inference_time_ms": pred.inference_time_ms,
        "evaluated_at": pred.evaluated_at.isoformat(),
        "status": "CACHED",
        "source": pred.source,
        "provenance_warning": pred.provenance_warning,
    }


def _dict_to_prediction(data: dict[str, Any]) -> MLFloodPrediction:
    return MLFloodPrediction(
        edge_id=UUID(data["edge_id"]),
        probability=float(data["probability"]),
        predicted_class=int(data["predicted_class"]),
        threshold=float(data["threshold"]),
        model_name=str(data["model_name"]),
        model_version=str(data["model_version"]),
        feature_version=str(data["feature_version"]),
        dataset_version=str(data["dataset_version"]),
        inference_time_ms=float(data["inference_time_ms"]),
        evaluated_at=datetime.fromisoformat(data["evaluated_at"]),
        status="CACHED",
        source=str(data.get("source", "ML")),
        provenance_warning=str(
            data.get(
                "provenance_warning",
                "SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.",
            )
        ),
    )


class MLPredictionCache:
    """Redis-backed cache for edge-level ML flood predictions."""

    def __init__(
        self,
        redis: Redis | None,
        ttl_seconds: int = 300,
        enabled: bool = True,
        metrics: CacheMetrics | None = None,
    ) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds
        self.enabled = enabled
        self.metrics = metrics or CacheMetrics()

    async def get_batch(
        self,
        graph_version_id: UUID | str,
        model_version: str,
        risk_revision: int,
        config_hash: str,
        edge_ids: list[UUID] | tuple[UUID, ...],
    ) -> tuple[dict[UUID, MLFloodPrediction], list[UUID]]:
        """Fetch cached predictions in batch.

        Returns (hits_dict, missing_edge_ids).
        """
        if not self.enabled or self.redis is None or not edge_ids:
            return {}, list(edge_ids)

        keys = [
            ml_prediction_cache_key(
                graph_version_id, model_version, risk_revision, edge_id, config_hash
            )
            for edge_id in edge_ids
        ]

        hits: dict[UUID, MLFloodPrediction] = {}
        misses: list[UUID] = []

        try:
            if hasattr(self.redis, "mget"):
                raw_items = await self.redis.mget(keys)
            else:
                raw_items = [await self.redis.get(k) for k in keys]
            for edge_id, raw in zip(edge_ids, raw_items, strict=True):
                if raw is not None:
                    try:
                        data = json.loads(raw)
                        hits[edge_id] = _dict_to_prediction(data)
                        if self.metrics:
                            self.metrics.record_hit("ml_prediction")
                    except Exception as err:
                        logger.warning("Corrupted ML cache entry for edge %s: %s", edge_id, err)
                        misses.append(edge_id)
                        if self.metrics:
                            self.metrics.record_error("ml_prediction")
                else:
                    misses.append(edge_id)
                    if self.metrics:
                        self.metrics.record_miss("ml_prediction")
        except Exception as err:
            logger.warning("Redis ML cache lookup failure: %s", err)
            if self.metrics:
                self.metrics.record_error("ml_prediction")
            return {}, list(edge_ids)

        return hits, misses

    async def set_batch(
        self,
        graph_version_id: UUID | str,
        model_version: str,
        risk_revision: int,
        config_hash: str,
        predictions: dict[UUID, MLFloodPrediction],
    ) -> None:
        """Store predictions in batch using Redis pipeline."""
        if not self.enabled or self.redis is None or not predictions:
            return

        try:
            if hasattr(self.redis, "pipeline"):
                async with self.redis.pipeline(transaction=False) as pipe:
                    for edge_id, pred in predictions.items():
                        key = ml_prediction_cache_key(
                            graph_version_id, model_version, risk_revision, edge_id, config_hash
                        )
                        payload = json.dumps(_prediction_to_dict(pred))
                        pipe.set(key, payload, ex=self.ttl_seconds)
                    await pipe.execute()
            else:
                for edge_id, pred in predictions.items():
                    key = ml_prediction_cache_key(
                        graph_version_id, model_version, risk_revision, edge_id, config_hash
                    )
                    payload = json.dumps(_prediction_to_dict(pred))
                    await self.redis.set(key, payload, ex=self.ttl_seconds)
            if self.metrics:
                self.metrics.record_set("ml_prediction")
        except Exception as err:
            logger.warning("Redis ML cache write failure: %s", err)
            if self.metrics:
                self.metrics.record_error("ml_prediction")

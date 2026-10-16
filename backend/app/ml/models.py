"""ML prediction domain models and telemetry metrics for Phase 13."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


class InvalidProbabilityError(ValueError):
    """Raised when an ML prediction probability is outside [0.0, 1.0] or non-finite."""


def validate_probability(probability: float) -> float:
    """Validate probability is finite and bounded in [0.0, 1.0]."""
    if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
        raise InvalidProbabilityError(
            f"Invalid probability value {probability}; must be finite and within [0.0, 1.0]."
        )
    return float(probability)


@dataclass(frozen=True)
class MLFloodPrediction:
    """Domain representation of a machine learning flood prediction on a road edge."""

    edge_id: UUID
    probability: float
    predicted_class: int
    threshold: float
    model_name: str
    model_version: str
    feature_version: str
    dataset_version: str
    inference_time_ms: float
    evaluated_at: datetime
    status: str = "SUCCESS"  # "SUCCESS", "CACHED", "FALLBACK"
    source: str = "ML"
    provenance_warning: str = (
        "SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy."
    )

    def __post_init__(self) -> None:
        validate_probability(self.probability)
        if self.predicted_class not in (0, 1):
            raise ValueError(f"predicted_class must be 0 or 1, got {self.predicted_class}")


@dataclass
class MLInferenceMetrics:
    """Telemetry counters for ML inference and caching performance."""

    predictions_total: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    inference_errors: int = 0
    schema_errors: int = 0
    total_inference_time_ms: float = 0.0
    shadow_disagreements: int = 0

    def record_hit(self) -> None:
        self.predictions_total += 1
        self.cache_hits += 1

    def record_miss(self, latency_ms: float) -> None:
        self.predictions_total += 1
        self.cache_misses += 1
        self.total_inference_time_ms += latency_ms

    def record_error(self) -> None:
        self.inference_errors += 1

    def record_schema_error(self) -> None:
        self.schema_errors += 1

    def record_shadow_disagreement(self) -> None:
        self.shadow_disagreements += 1

    @property
    def avg_inference_latency_ms(self) -> float:
        if self.cache_misses == 0:
            return 0.0
        return round(self.total_inference_time_ms / self.cache_misses, 3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "predictions_total": self.predictions_total,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "inference_errors": self.inference_errors,
            "schema_errors": self.schema_errors,
            "avg_inference_latency_ms": self.avg_inference_latency_ms,
            "shadow_disagreements": self.shadow_disagreements,
        }

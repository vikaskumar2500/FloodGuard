"""Deterministic rule-based baseline model.

Provides a non-ML benchmark to compare against learned models.
Rule:
Predict flood if latest observed water depth >= depth_threshold (default 15cm)
OR current rainfall rate >= rain_threshold (default 30 mm/h).
"""

from __future__ import annotations

from typing import Any

import numpy as np


class RuleBasedFloodBaseline:
    """Heuristic rule-based baseline for flood prediction."""

    def __init__(
        self,
        water_depth_threshold_cm: float = 15.0,
        rainfall_threshold_mm_h: float = 30.0,
    ) -> None:
        self.water_depth_threshold_cm = water_depth_threshold_cm
        self.rainfall_threshold_mm_h = rainfall_threshold_mm_h

    def fit(self, X: Any, y: Any = None) -> RuleBasedFloodBaseline:
        """No parameters to learn; exists for API compatibility."""
        return self

    def predict_proba(self, records: list[dict[str, Any]]) -> np.ndarray:
        """Return 2D probability array [[prob_0, prob_1], ...]."""
        probs = []
        for r in records:
            depth = r.get("water_depth_current_cm")
            rain = r.get("rainfall_rate_now_mm_h")

            rule_triggered = (
                (depth is not None and depth >= self.water_depth_threshold_cm)
                or (rain is not None and rain >= self.rainfall_threshold_mm_h)
            )

            # Assign high probability if triggered, low if not
            p1 = 0.90 if rule_triggered else 0.10
            probs.append([1.0 - p1, p1])

        return np.array(probs, dtype=np.float64)

    def predict(self, records: list[dict[str, Any]], threshold: float = 0.5) -> np.ndarray:
        """Return binary predictions [0, 1]."""
        proba = self.predict_proba(records)
        return (proba[:, 1] >= threshold).astype(np.int64)


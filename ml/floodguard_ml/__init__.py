"""FloodGuard Phase 11 — ML Dataset & Feature Engineering Pipeline.

Provides code-driven, reproducible dataset generation for flood prediction models.
Follows strict contracts:
- Prediction unit: (road_edge, timestamp)
- Feature timestamps: <= T
- Prediction target: will edge experience HIGH/SEVERE flood risk in (T, T + horizon]
- Missing values: None is strictly distinguished from 0.0
- Provenance: SYNTHETIC, REAL, or MIXED explicitly recorded
- Splits: strictly chronological without temporal leakage
"""

from .config.feature_config import FeatureConfig
from .features.schema import FEATURE_SCHEMA_V1, FEATURE_VERSION

__all__ = [
    "FEATURE_SCHEMA_V1",
    "FEATURE_VERSION",
    "FeatureConfig",
]


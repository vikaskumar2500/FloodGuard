"""XGBoost classifier pipeline for flood prediction."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from xgboost import XGBClassifier

from floodguard_ml.models.preprocessing import (
    build_preprocessor,
    get_transformed_feature_names,
)
from floodguard_ml.models.selection import MODEL_FEATURES_V1


class XGBoostFloodModel:
    """XGBoost classifier pipeline with conservative hyperparameters for small datasets."""

    def __init__(
        self,
        n_estimators: int = 50,
        max_depth: int = 3,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        min_child_weight: float = 2.0,
        scale_pos_weight: float = 1.0,
        random_state: int = 42,
    ) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.subsample = subsample
        self.colsample_bytree = colsample_bytree
        self.min_child_weight = min_child_weight
        self.scale_pos_weight = scale_pos_weight
        self.random_state = random_state

        # Trees do not require StandardScaler, so scale_numeric=False
        self.preprocessor = build_preprocessor(scale_numeric=False)
        self.classifier = XGBClassifier(
            n_estimators=self.n_estimators,
            max_depth=self.max_depth,
            learning_rate=self.learning_rate,
            subsample=self.subsample,
            colsample_bytree=self.colsample_bytree,
            min_child_weight=self.min_child_weight,
            scale_pos_weight=self.scale_pos_weight,
            random_state=self.random_state,
            eval_metric="logloss",
        )
        self.pipeline = Pipeline(
            steps=[
                ("preprocessor", self.preprocessor),
                ("classifier", self.classifier),
            ]
        )
        self.transformed_feature_names: list[str] = []

    def fit(self, records: list[dict[str, Any]], y: np.ndarray) -> XGBoostFloodModel:
        """Fit preprocessor and XGBoost classifier on training data."""
        df = pd.DataFrame([{f: r.get(f) for f in MODEL_FEATURES_V1} for r in records])
        self.pipeline.fit(df, y)
        self.transformed_feature_names = get_transformed_feature_names(
            self.pipeline.named_steps["preprocessor"]
        )
        return self

    def predict_proba(self, records: list[dict[str, Any]]) -> np.ndarray:
        """Return class probability estimates [[prob_0, prob_1], ...]."""
        df = pd.DataFrame([{f: r.get(f) for f in MODEL_FEATURES_V1} for r in records])
        return self.pipeline.predict_proba(df)

    def predict(self, records: list[dict[str, Any]], threshold: float = 0.5) -> np.ndarray:
        """Return binary class predictions based on decision threshold."""
        proba = self.predict_proba(records)
        return (proba[:, 1] >= threshold).astype(np.int64)

    def get_feature_importances(self) -> list[dict[str, Any]]:
        """Return XGBoost gain-based feature importances sorted descending."""
        if not hasattr(self.classifier, "feature_importances_"):
            return []
        importances = self.classifier.feature_importances_
        results = []
        for name, imp in zip(self.transformed_feature_names, importances):
            results.append({
                "feature": name,
                "importance": round(float(imp), 4),
            })
        results.sort(key=lambda x: x["importance"], reverse=True)
        return results


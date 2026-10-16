"""Logistic Regression baseline classifier for flood prediction."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from floodguard_ml.models.preprocessing import (
    build_preprocessor,
    get_transformed_feature_names,
)
from floodguard_ml.models.selection import MODEL_FEATURES_V1


class LogisticRegressionFloodModel:
    """Logistic regression classifier pipeline with median imputation and standardization."""

    def __init__(
        self,
        C: float = 1.0,
        max_iter: int = 1000,
        class_weight: str | dict | None = "balanced",
        random_state: int = 42,
    ) -> None:
        self.C = C
        self.max_iter = max_iter
        self.class_weight = class_weight
        self.random_state = random_state

        self.preprocessor = build_preprocessor(scale_numeric=True)
        self.classifier = LogisticRegression(
            C=self.C,
            max_iter=self.max_iter,
            class_weight=self.class_weight,
            random_state=self.random_state,
            solver="lbfgs",
        )
        self.pipeline = Pipeline(
            steps=[
                ("preprocessor", self.preprocessor),
                ("classifier", self.classifier),
            ]
        )
        self.transformed_feature_names: list[str] = []

    def fit(self, records: list[dict[str, Any]], y: np.ndarray) -> LogisticRegressionFloodModel:
        """Fit preprocessing transformations and logistic classifier on training data."""
        # Convert records to DataFrame-like structure for ColumnTransformer
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
        """Return standardized coefficients sorted by absolute predictive importance."""
        if not hasattr(self.classifier, "coef_"):
            return []
        coefs = self.classifier.coef_[0]
        results = []
        for name, coef in zip(self.transformed_feature_names, coefs):
            results.append({
                "feature": name,
                "importance": round(float(coef), 4),
                "abs_importance": round(float(abs(coef)), 4),
            })
        results.sort(key=lambda x: x["abs_importance"], reverse=True)
        return results


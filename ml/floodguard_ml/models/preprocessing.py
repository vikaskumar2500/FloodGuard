"""Reproducible preprocessing pipelines for FloodGuard ML models.

Contract:
Preprocessing transformations MUST be fitted on TRAIN only.
Validation and test sets must only be transformed using the train-fitted pipeline.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from floodguard_ml.models.selection import (
    BOOLEAN_FEATURES_V1,
    CATEGORICAL_FEATURES_V1,
    MODEL_FEATURES_V1,
    NUMERIC_FEATURES_V1,
)


class BooleanToNumeric(BaseEstimator, TransformerMixin):
    """Convert boolean indicator features to float (0.0, 1.0, np.nan) for imputation."""

    def fit(self, X: Any, y: Any = None) -> BooleanToNumeric:
        return self

    def transform(self, X: Any) -> np.ndarray:
        if hasattr(X, "astype"):
            return X.astype(float)
        return np.asarray(X, dtype=float)

    def get_feature_names_out(self, input_features: Any = None) -> Any:
        return input_features


def extract_raw_matrices(
    records: list[dict[str, Any]],
    feature_names: tuple[str, ...] = MODEL_FEATURES_V1,
    target_name: str = "target_flooded_within_horizon",
) -> tuple[dict[str, list[Any]], np.ndarray | None]:
    """Extract feature dictionary and target array from dataset records."""
    feature_dict: dict[str, list[Any]] = {f: [] for f in feature_names}
    targets: list[int] = []

    for r in records:
        for f in feature_names:
            feature_dict[f].append(r.get(f))
        if target_name in r:
            targets.append(int(r[target_name]))

    y = np.array(targets, dtype=np.int64) if targets else None
    return feature_dict, y


def build_preprocessor(scale_numeric: bool = True) -> ColumnTransformer:
    """Build a ColumnTransformer for ModelFeaturesV1.

    Args:
        scale_numeric: If True, applies StandardScaler (recommended for Logistic Regression).
                       If False, leaves numeric values unscaled (standard for tree models).
    """
    numeric_steps: list[tuple[str, Any]] = [
        ("imputer", SimpleImputer(strategy="median")),
    ]
    if scale_numeric:
        numeric_steps.append(("scaler", StandardScaler()))

    numeric_transformer = Pipeline(steps=numeric_steps)

    categorical_transformer = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="UNKNOWN")),
            ("onehot", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ]
    )

    boolean_transformer = Pipeline(
        steps=[
            ("cast", BooleanToNumeric()),
            ("imputer", SimpleImputer(strategy="most_frequent")),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", numeric_transformer, list(NUMERIC_FEATURES_V1)),
            ("cat", categorical_transformer, list(CATEGORICAL_FEATURES_V1)),
            ("bool", boolean_transformer, list(BOOLEAN_FEATURES_V1)),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    return preprocessor


def get_transformed_feature_names(preprocessor: ColumnTransformer) -> list[str]:
    """Retrieve output feature names from a fitted ColumnTransformer."""
    names: list[str] = []
    # Numeric features
    names.extend(list(NUMERIC_FEATURES_V1))

    # Categorical features from OneHotEncoder
    cat_step = preprocessor.named_transformers_["cat"]
    if hasattr(cat_step, "named_steps") and "onehot" in cat_step.named_steps:
        encoder = cat_step.named_steps["onehot"]
        if hasattr(encoder, "get_feature_names_out"):
            cat_names = encoder.get_feature_names_out(list(CATEGORICAL_FEATURES_V1))
            names.extend(list(cat_names))
        else:
            names.extend(list(CATEGORICAL_FEATURES_V1))
    else:
        names.extend(list(CATEGORICAL_FEATURES_V1))

    # Boolean features
    names.extend(list(BOOLEAN_FEATURES_V1))
    return names


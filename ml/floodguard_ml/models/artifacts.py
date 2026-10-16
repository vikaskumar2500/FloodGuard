"""Artifact persistence and loading for FloodGuard ML models.

Contract:
- Model binaries persisted via joblib with SHA-256 integrity check.
- Complete metadata, metrics, threshold, feature schema, and feature importances persisted alongside model.
- LoadedFloodModel provides runtime validation, schema enforcement, and inference.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from floodguard_ml.io.readers import read_json
from floodguard_ml.io.writers import write_json
from floodguard_ml.models.evaluation import ModelMetrics
from floodguard_ml.models.selection import MODEL_FEATURES_V1


def compute_file_sha256(filepath: str | Path) -> str:
    """Calculate SHA-256 checksum of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class ModelSchemaError(Exception):
    """Raised when input records do not match the expected feature schema."""


class ModelIntegrityError(Exception):
    """Raised when model artifact checksum does not match metadata."""


def save_model_artifacts(
    model: Any,
    model_version: str,
    model_type: str,
    output_dir: str | Path,
    dataset_version: str,
    dataset_content_hash: str,
    hyperparameters: dict[str, Any],
    threshold: float,
    threshold_analysis: list[dict[str, Any]],
    metrics: dict[str, ModelMetrics],
    feature_importances: list[dict[str, Any]],
    feature_names: tuple[str, ...] = MODEL_FEATURES_V1,
) -> Path:
    """Persist trained model and associated metadata artifacts.

    Returns the directory path where artifacts are saved.
    """
    out_dir = Path(output_dir) / model_version
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Save model binary
    model_path = out_dir / "model.joblib"
    joblib.dump(model, model_path)
    sha256 = compute_file_sha256(model_path)

    # 2. Save metadata.json
    metadata = {
        "model_version": model_version,
        "model_type": model_type,
        "trained_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "dataset_version": dataset_version,
        "dataset_content_hash": dataset_content_hash,
        "model_sha256": sha256,
        "hyperparameters": hyperparameters,
        "provenance_warning": "SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.",
        "input_feature_count": len(feature_names),
    }
    write_json(metadata, out_dir / "metadata.json")

    # 3. Save metrics.json
    serialized_metrics = {
        split_name: asdict(m) for split_name, m in metrics.items()
    }
    write_json(serialized_metrics, out_dir / "metrics.json")

    # 4. Save threshold.json
    threshold_meta = {
        "selected_threshold": threshold,
        "selection_policy": "F1 maximization subject to recall >= 0.70 on validation set",
        "validation_threshold_tuning": threshold_analysis,
    }
    write_json(threshold_meta, out_dir / "threshold.json")

    # 5. Save feature_schema.json
    schema_meta = {
        "feature_names": list(feature_names),
        "feature_count": len(feature_names),
        "expected_columns": list(feature_names),
    }
    write_json(schema_meta, out_dir / "feature_schema.json")

    # 6. Save feature_importance.json
    write_json({"feature_importances": feature_importances}, out_dir / "feature_importance.json")

    return out_dir


class LoadedFloodModel:
    """Loaded model wrapper for offline inference and evaluation."""

    def __init__(
        self,
        model: Any,
        metadata: dict[str, Any],
        threshold: float,
        feature_schema: dict[str, Any],
        feature_importances: list[dict[str, Any]],
        model_dir: Path,
    ) -> None:
        self.model = model
        self.metadata = metadata
        self.threshold = threshold
        self.feature_schema = feature_schema
        self.feature_importances = feature_importances
        self.model_dir = model_dir
        self.expected_features: list[str] = feature_schema.get("feature_names", list(MODEL_FEATURES_V1))

    @classmethod
    def load(cls, artifact_dir: str | Path, verify_checksum: bool = True) -> LoadedFloodModel:
        """Load model and metadata from artifact directory."""
        dir_path = Path(artifact_dir)
        model_path = dir_path / "model.joblib"
        meta_path = dir_path / "metadata.json"
        threshold_path = dir_path / "threshold.json"
        schema_path = dir_path / "feature_schema.json"
        imp_path = dir_path / "feature_importance.json"

        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found at {model_path}")
        if not meta_path.exists():
            raise FileNotFoundError(f"Metadata file not found at {meta_path}")

        metadata = read_json(meta_path)

        if verify_checksum:
            expected_sha256 = metadata.get("model_sha256")
            actual_sha256 = compute_file_sha256(model_path)
            if expected_sha256 and actual_sha256 != expected_sha256:
                raise ModelIntegrityError(
                    f"Model SHA-256 integrity mismatch! Expected {expected_sha256}, got {actual_sha256}."
                )

        model = joblib.load(model_path)
        threshold_meta = read_json(threshold_path) if threshold_path.exists() else {}
        selected_threshold = float(threshold_meta.get("selected_threshold", 0.5))
        schema_meta = read_json(schema_path) if schema_path.exists() else {}
        imp_meta = read_json(imp_path) if imp_path.exists() else {}

        return cls(
            model=model,
            metadata=metadata,
            threshold=selected_threshold,
            feature_schema=schema_meta,
            feature_importances=imp_meta.get("feature_importances", []),
            model_dir=dir_path,
        )

    def validate_input(self, records: list[dict[str, Any]]) -> None:
        """Validate input records against the expected feature schema.

        Warns or raises ModelSchemaError if essential features are completely missing.
        """
        if not records:
            return
        sample = records[0]
        missing_keys = [f for f in self.expected_features if f not in sample]
        if missing_keys:
            # Check if all features are missing (e.g. completely wrong input schema)
            if len(missing_keys) == len(self.expected_features):
                raise ModelSchemaError(
                    f"All expected model features are missing from input! Expected: {self.expected_features[:5]}..."
                )

    def predict_proba(self, records: list[dict[str, Any]]) -> np.ndarray:
        """Predict positive class probabilities for input records."""
        self.validate_input(records)
        return self.model.predict_proba(records)

    def predict(
        self,
        records: list[dict[str, Any]],
        threshold: float | None = None,
    ) -> np.ndarray:
        """Predict binary flood classifications."""
        th = threshold if threshold is not None else self.threshold
        proba = self.predict_proba(records)
        return (proba[:, 1] >= th).astype(np.int64)


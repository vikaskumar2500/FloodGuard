"""Unit and integration tests for Phase 12 ML models.

Covers:
- Feature leakage audit
- Preprocessor behavior (numeric scaling, categorical encoding, median imputation)
- Rule-based baseline logic
- Logistic regression pipeline & standardized coefficients
- XGBoost pipeline & gain feature importances
- Validation-only threshold selection
- Artifact persistence, SHA-256 verification, and reload predictability
- Schema enforcement and tampering detection
- Latency benchmarking and scenario holdout
- CLI subcommands: train, compare-models
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from floodguard_ml.cli import main
from floodguard_ml.io.readers import read_parquet
from floodguard_ml.models.artifacts import (
    LoadedFloodModel,
    ModelIntegrityError,
    ModelSchemaError,
    save_model_artifacts,
)
from floodguard_ml.models.baseline import RuleBasedFloodBaseline
from floodguard_ml.models.evaluation import (
    evaluate_predictions,
    select_optimal_threshold,
)
from floodguard_ml.models.logistic import LogisticRegressionFloodModel
from floodguard_ml.models.preprocessing import (
    build_preprocessor,
    extract_raw_matrices,
)
from floodguard_ml.models.selection import (
    EXCLUDED_COLUMNS_V1,
    MODEL_FEATURES_V1,
    FeatureLeakageAuditError,
    audit_feature_leakage,
)
from floodguard_ml.models.training import (
    benchmark_latency,
    evaluate_scenario_holdout,
    train_and_compare_all_models,
    train_and_evaluate_model,
)
from floodguard_ml.models.xgboost_model import XGBoostFloodModel


@pytest.fixture
def synthetic_records() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Load train, val, test records from existing synthetic-v1 dataset."""
    dataset_dir = Path("data/processed/synthetic-v1")
    train = read_parquet(dataset_dir / "train.parquet")
    val = read_parquet(dataset_dir / "validation.parquet")
    test = read_parquet(dataset_dir / "test.parquet")
    return train, val, test


class TestFeatureLeakageAudit:
    def test_clean_features_pass(self) -> None:
        """Standard MODEL_FEATURES_V1 must pass leakage audit."""
        audit_feature_leakage(MODEL_FEATURES_V1)

    def test_target_raises_leakage_error(self) -> None:
        """Any feature containing 'target' must be rejected."""
        with pytest.raises(FeatureLeakageAuditError, match="forbidden pattern"):
            audit_feature_leakage(["rainfall_rate_now_mm_h", "target_flooded"])

    def test_excluded_columns_raise_leakage_error(self) -> None:
        """Any column explicitly marked for exclusion must be rejected."""
        for col in EXCLUDED_COLUMNS_V1:
            with pytest.raises(FeatureLeakageAuditError):
                audit_feature_leakage([col])


class TestPreprocessing:
    def test_preprocessor_fitting(self, synthetic_records: Any) -> None:
        train, val, _ = synthetic_records
        preprocessor = build_preprocessor(scale_numeric=True)

        import pandas as pd
        df_train = pd.DataFrame([{f: r.get(f) for f in MODEL_FEATURES_V1} for r in train])
        df_val = pd.DataFrame([{f: r.get(f) for f in MODEL_FEATURES_V1} for r in val])

        # Preprocessor fit on train only
        X_train = preprocessor.fit_transform(df_train)
        assert X_train.shape[0] == len(train)
        assert not np.isnan(X_train).any()

        # Transform on val
        X_val = preprocessor.transform(df_val)
        assert X_val.shape[0] == len(val)
        assert not np.isnan(X_val).any()

    def test_extract_raw_matrices(self, synthetic_records: Any) -> None:
        train, _, _ = synthetic_records
        f_dict, y = extract_raw_matrices(train)
        assert y is not None
        assert len(y) == len(train)
        assert "rainfall_rate_now_mm_h" in f_dict


class TestRuleBasedBaseline:
    def test_baseline_logic(self) -> None:
        baseline = RuleBasedFloodBaseline(water_depth_threshold_cm=15.0, rainfall_threshold_mm_h=30.0)

        # Dry record
        dry = [{"water_depth_current_cm": 2.0, "rainfall_rate_now_mm_h": 5.0}]
        probs_dry = baseline.predict_proba(dry)
        assert probs_dry[0, 1] == 0.10
        assert baseline.predict(dry)[0] == 0

        # Flooded by depth
        flooded_depth = [{"water_depth_current_cm": 20.0, "rainfall_rate_now_mm_h": 0.0}]
        probs_flood = baseline.predict_proba(flooded_depth)
        assert probs_flood[0, 1] == 0.90
        assert baseline.predict(flooded_depth)[0] == 1

        # Flooded by rain
        flooded_rain = [{"water_depth_current_cm": None, "rainfall_rate_now_mm_h": 45.0}]
        assert baseline.predict(flooded_rain)[0] == 1


class TestLogisticRegression:
    def test_logistic_fit_and_predict(self, synthetic_records: Any) -> None:
        train, val, _ = synthetic_records
        y_train = np.array([int(r["target_flooded_within_horizon"]) for r in train], dtype=np.int64)

        model = LogisticRegressionFloodModel(random_state=42)
        model.fit(train, y_train)

        probs = model.predict_proba(val)
        assert probs.shape == (len(val), 2)
        np.testing.assert_allclose(probs.sum(axis=1), np.ones(len(val)), rtol=1e-5)

        preds = model.predict(val, threshold=0.5)
        assert set(preds).issubset({0, 1})

        importances = model.get_feature_importances()
        assert len(importances) > 0
        assert "feature" in importances[0]
        assert "importance" in importances[0]
        # Sorted descending by absolute importance
        abs_vals = [i["abs_importance"] for i in importances]
        assert abs_vals == sorted(abs_vals, reverse=True)


class TestXGBoostModel:
    def test_xgboost_fit_and_predict(self, synthetic_records: Any) -> None:
        train, val, _ = synthetic_records
        y_train = np.array([int(r["target_flooded_within_horizon"]) for r in train], dtype=np.int64)

        model = XGBoostFloodModel(n_estimators=10, max_depth=2, random_state=42)
        model.fit(train, y_train)

        probs = model.predict_proba(val)
        assert probs.shape == (len(val), 2)
        assert (probs[:, 1] >= 0.0).all() and (probs[:, 1] <= 1.0).all()

        importances = model.get_feature_importances()
        assert len(importances) > 0
        vals = [i["importance"] for i in importances]
        assert vals == sorted(vals, reverse=True)


class TestEvaluationAndThresholding:
    def test_metrics_calculation(self) -> None:
        y_true = np.array([0, 0, 1, 1, 1], dtype=np.int64)
        y_prob = np.array([0.1, 0.4, 0.8, 0.9, 0.3], dtype=np.float64)

        metrics = evaluate_predictions(y_true, y_prob, threshold=0.5)
        assert metrics.total_samples == 5
        assert metrics.positive_samples == 3
        assert metrics.negative_samples == 2
        assert metrics.confusion_matrix["TP"] == 2
        assert metrics.confusion_matrix["FN"] == 1
        assert metrics.confusion_matrix["TN"] == 2
        assert metrics.confusion_matrix["FP"] == 0
        assert metrics.precision == 1.0
        assert round(metrics.recall, 2) == 0.67
        assert "SYNTHETIC DATASET EVALUATION" in metrics.provenance_warning

    def test_threshold_selection_validation_only(self) -> None:
        y_val = np.array([0, 0, 1, 1], dtype=np.int64)
        y_prob_val = np.array([0.1, 0.2, 0.35, 0.8], dtype=np.float64)

        # At th=0.3: TP=2, FP=0 -> Recall=1.0, Precision=1.0, F1=1.0
        # At th=0.5: TP=1, FP=0, FN=1 -> Recall=0.5
        best_th, analysis = select_optimal_threshold(y_val, y_prob_val, candidate_thresholds=(0.3, 0.5), min_recall=0.70)
        assert best_th == 0.3
        assert len(analysis) == 2


class TestArtifactsAndPersistence:
    def test_save_and_reload_model(self, synthetic_records: Any) -> None:
        train, val, test = synthetic_records
        y_train = np.array([int(r["target_flooded_within_horizon"]) for r in train], dtype=np.int64)

        model = LogisticRegressionFloodModel(random_state=42)
        model.fit(train, y_train)

        metrics = evaluate_predictions(y_train, model.predict_proba(train)[:, 1])

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = save_model_artifacts(
                model=model,
                model_version="test-logistic-v1",
                model_type="logistic",
                output_dir=tmpdir,
                dataset_version="synthetic-test",
                dataset_content_hash="hash123",
                hyperparameters={"C": 1.0},
                threshold=0.45,
                threshold_analysis=[],
                metrics={"train": metrics},
                feature_importances=[],
            )

            # Check files exist
            assert (out_dir / "model.joblib").exists()
            assert (out_dir / "metadata.json").exists()
            assert (out_dir / "metrics.json").exists()
            assert (out_dir / "threshold.json").exists()
            assert (out_dir / "feature_schema.json").exists()
            assert (out_dir / "feature_importance.json").exists()

            # Load model back
            loaded = LoadedFloodModel.load(out_dir)
            assert loaded.threshold == 0.45
            assert loaded.metadata["model_version"] == "test-logistic-v1"

            # Check predictions are identical
            orig_probs = model.predict_proba(test)
            loaded_probs = loaded.predict_proba(test)
            np.testing.assert_allclose(orig_probs, loaded_probs)

            # Check integrity error on corrupted file
            with open(out_dir / "model.joblib", "ab") as f:
                f.write(b"tamper")

            with pytest.raises(ModelIntegrityError):
                LoadedFloodModel.load(out_dir, verify_checksum=True)

    def test_schema_error_on_missing_features(self, synthetic_records: Any) -> None:
        train, _, _ = synthetic_records
        y_train = np.array([int(r["target_flooded_within_horizon"]) for r in train], dtype=np.int64)

        model = LogisticRegressionFloodModel(random_state=42)
        model.fit(train, y_train)

        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = save_model_artifacts(
                model=model,
                model_version="test-v1",
                model_type="logistic",
                output_dir=tmpdir,
                dataset_version="synthetic-test",
                dataset_content_hash="hash123",
                hyperparameters={},
                threshold=0.5,
                threshold_analysis=[],
                metrics={},
                feature_importances=[],
            )
            loaded = LoadedFloodModel.load(out_dir)

            # Completely wrong schema should raise ModelSchemaError
            with pytest.raises(ModelSchemaError):
                loaded.predict_proba([{"completely_unrelated": 123}])


class TestTrainingAndComparison:
    def test_train_and_evaluate_model(self, synthetic_records: Any) -> None:
        train, val, test = synthetic_records
        res = train_and_evaluate_model("xgboost", train, val, test)

        assert res.model_name == "XGBoost Classifier"
        assert res.selected_threshold in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
        assert 0.0 <= res.test_metrics.f1 <= 1.0
        assert res.single_inference_latency_ms >= 0.0
        assert res.batch_inference_latency_ms >= 0.0

    def test_train_and_compare_all_models(self, synthetic_records: Any) -> None:
        train, val, test = synthetic_records
        # Run without holdout for speed in unit test
        results = train_and_compare_all_models(train, val, test, run_holdout=False)

        assert set(results.keys()) == {"baseline", "logistic", "xgboost"}
        for k, res in results.items():
            assert res.test_metrics.total_samples == len(test)

    def test_scenario_holdout(self) -> None:
        metrics = evaluate_scenario_holdout(
            model_type="logistic",
            train_scenarios=("NORMAL", "MODERATE_RAIN", "SEVERE_RAIN", "RECOVERY"),
            holdout_scenario="FLASH_FLOOD",
        )
        assert metrics.total_samples > 0
        assert 0.0 <= metrics.f1 <= 1.0

    def test_latency_benchmarking(self, synthetic_records: Any) -> None:
        train, _, test = synthetic_records
        baseline = RuleBasedFloodBaseline()
        single_ms, batch_ms = benchmark_latency(baseline, test, repetitions=20)
        assert single_ms >= 0.0
        assert batch_ms >= 0.0

    def test_determinism_fixed_seed(self, synthetic_records: Any) -> None:
        train, _, test = synthetic_records
        y_train = np.array([int(r["target_flooded_within_horizon"]) for r in train], dtype=np.int64)

        m1 = XGBoostFloodModel(random_state=42)
        m1.fit(train, y_train)
        p1 = m1.predict_proba(test)

        m2 = XGBoostFloodModel(random_state=42)
        m2.fit(train, y_train)
        p2 = m2.predict_proba(test)

        np.testing.assert_allclose(p1, p2)


class TestCLISubcommands:
    def test_cli_train_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            code = main([
                "train",
                "--dataset", "data/processed/synthetic-v1",
                "--model", "xgboost",
                "--output", tmpdir,
            ])
            assert code == 0
            assert (Path(tmpdir) / "xgboost-v1" / "model.joblib").exists()
            assert (Path(tmpdir) / "xgboost-v1" / "metadata.json").exists()

    def test_cli_compare_models_cmd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            code = main([
                "compare-models",
                "--dataset", "data/processed/synthetic-v1",
                "--output", tmpdir,
            ])
            assert code == 0
            assert (Path(tmpdir) / "comparison_report.json").exists()
            assert (Path(tmpdir) / "baseline-v1" / "model.joblib").exists()
            assert (Path(tmpdir) / "logistic-v1" / "model.joblib").exists()
            assert (Path(tmpdir) / "xgboost-v1" / "model.joblib").exists()


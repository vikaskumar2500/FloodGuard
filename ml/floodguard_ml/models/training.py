"""Model training orchestration, evaluation, comparison, and latency benchmarking.

Contract:
- Preprocessor and model fit exclusively on TRAIN split.
- Threshold selection performed exclusively on VALIDATION split.
- Final performance reported on TEST split using validation-tuned threshold.
- All evaluation outputs prominently marked with SYNTHETIC DATASET EVALUATION provenance.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from floodguard_ml.config.feature_config import FeatureConfig
from floodguard_ml.datasets.builder import DatasetBuilder
from floodguard_ml.datasets.sources import SimulationSource
from floodguard_ml.models.baseline import RuleBasedFloodBaseline
from floodguard_ml.models.evaluation import (
    ModelMetrics,
    evaluate_predictions,
    select_optimal_threshold,
)
from floodguard_ml.models.logistic import LogisticRegressionFloodModel
from floodguard_ml.models.xgboost_model import XGBoostFloodModel

logger = logging.getLogger("floodguard_ml.training")


@dataclass
class ModelTrainingResult:
    """Consolidated outcome of model training, threshold tuning, and evaluation."""

    model_name: str
    model_type: str
    model: Any
    hyperparameters: dict[str, Any]
    selected_threshold: float
    threshold_analysis: list[dict[str, Any]]
    train_metrics: ModelMetrics
    val_metrics: ModelMetrics
    test_metrics: ModelMetrics
    feature_importances: list[dict[str, Any]]
    single_inference_latency_ms: float
    batch_inference_latency_ms: float
    scenario_holdout_metrics: ModelMetrics | None = None


def benchmark_latency(
    model: Any,
    records: list[dict[str, Any]],
    repetitions: int = 100,
) -> tuple[float, float]:
    """Measure single-record median latency and full-batch latency in milliseconds.

    Returns:
        (median_single_row_ms, batch_latency_ms)
    """
    if not records:
        return 0.0, 0.0

    sample = [records[0]]

    # Warmup
    for _ in range(5):
        model.predict_proba(sample)

    # 1. Single-row latency benchmarking
    latencies: list[float] = []
    for _ in range(repetitions):
        t0 = time.perf_counter()
        model.predict_proba(sample)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000.0)

    median_single_ms = float(np.median(latencies))

    # 2. Batch latency benchmarking
    t0_batch = time.perf_counter()
    model.predict_proba(records)
    t1_batch = time.perf_counter()
    batch_ms = (t1_batch - t0_batch) * 1000.0

    return round(median_single_ms, 3), round(batch_ms, 3)


def train_and_evaluate_model(
    model_type: str,
    train_records: list[dict[str, Any]],
    val_records: list[dict[str, Any]],
    test_records: list[dict[str, Any]],
    hyperparameters: dict[str, Any] | None = None,
    min_recall: float = 0.70,
) -> ModelTrainingResult:
    """Train single model, select threshold on validation set, and evaluate on test set."""
    hparams = hyperparameters or {}

    y_train = np.array([int(r["target_flooded_within_horizon"]) for r in train_records], dtype=np.int64)
    y_val = np.array([int(r["target_flooded_within_horizon"]) for r in val_records], dtype=np.int64)
    y_test = np.array([int(r["target_flooded_within_horizon"]) for r in test_records], dtype=np.int64)

    # Instantiate model
    model: Any
    if model_type == "baseline":
        model = RuleBasedFloodBaseline(**hparams)
        model_name = "Rule-Based Baseline"
    elif model_type == "logistic":
        model = LogisticRegressionFloodModel(**hparams)
        model_name = "Logistic Regression"
    elif model_type == "xgboost":
        model = XGBoostFloodModel(**hparams)
        model_name = "XGBoost Classifier"
    else:
        raise ValueError(f"Unknown model_type: '{model_type}'. Choose from 'baseline', 'logistic', 'xgboost'.")

    # Fit exclusively on train records
    logger.info("fitting_model", extra={"model_type": model_type, "train_rows": len(train_records)})
    model.fit(train_records, y_train)

    # Predict probabilities across splits
    train_probs = model.predict_proba(train_records)[:, 1]
    val_probs = model.predict_proba(val_records)[:, 1]
    test_probs = model.predict_proba(test_records)[:, 1]

    # Select optimal decision threshold EXCLUSIVELY on validation split
    selected_threshold, threshold_analysis = select_optimal_threshold(
        y_true=y_val,
        y_prob=val_probs,
        candidate_thresholds=(0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8),
        min_recall=min_recall,
    )

    # Compute metrics using selected threshold
    train_metrics = evaluate_predictions(y_train, train_probs, threshold=selected_threshold)
    val_metrics = evaluate_predictions(y_val, val_probs, threshold=selected_threshold)
    test_metrics = evaluate_predictions(y_test, test_probs, threshold=selected_threshold)

    # Feature importances
    feature_importances: list[dict[str, Any]] = []
    if hasattr(model, "get_feature_importances"):
        feature_importances = model.get_feature_importances()

    # Benchmark latencies on test set
    single_ms, batch_ms = benchmark_latency(model, test_records)

    return ModelTrainingResult(
        model_name=model_name,
        model_type=model_type,
        model=model,
        hyperparameters=hparams,
        selected_threshold=selected_threshold,
        threshold_analysis=threshold_analysis,
        train_metrics=train_metrics,
        val_metrics=val_metrics,
        test_metrics=test_metrics,
        feature_importances=feature_importances,
        single_inference_latency_ms=single_ms,
        batch_inference_latency_ms=batch_ms,
    )


def evaluate_scenario_holdout(
    model_type: str,
    train_scenarios: tuple[str, ...] = ("NORMAL", "MODERATE_RAIN", "SEVERE_RAIN", "RECOVERY"),
    holdout_scenario: str = "FLASH_FLOOD",
    seed: int = 42,
    config: FeatureConfig | None = None,
) -> ModelMetrics:
    """Train on a subset of scenarios and evaluate generalization on a held-out scenario."""
    cfg = config or FeatureConfig()
    builder = DatasetBuilder(config=cfg)

    # Train data: subset scenarios
    source_train = SimulationSource(scenarios=train_scenarios, seed=seed)
    train_records = builder.build_records(source_train)
    y_train = np.array([int(r["target_flooded_within_horizon"]) for r in train_records], dtype=np.int64)

    # Test data: holdout scenario
    source_holdout = SimulationSource(scenarios=(holdout_scenario,), seed=seed)
    holdout_records = builder.build_records(source_holdout)
    y_holdout = np.array([int(r["target_flooded_within_horizon"]) for r in holdout_records], dtype=np.int64)

    if model_type == "logistic":
        model = LogisticRegressionFloodModel(random_state=seed)
    elif model_type == "xgboost":
        model = XGBoostFloodModel(random_state=seed)
    else:
        model = RuleBasedFloodBaseline()

    model.fit(train_records, y_train)
    holdout_probs = model.predict_proba(holdout_records)[:, 1]

    # Evaluate at default 0.5 threshold on holdout
    return evaluate_predictions(y_holdout, holdout_probs, threshold=0.5)


def train_and_compare_all_models(
    train_records: list[dict[str, Any]],
    val_records: list[dict[str, Any]],
    test_records: list[dict[str, Any]],
    run_holdout: bool = True,
) -> dict[str, ModelTrainingResult]:
    """Train and evaluate Baseline, Logistic Regression, and XGBoost models.

    Returns dictionary mapping model_type -> ModelTrainingResult.
    """
    model_types = ["baseline", "logistic", "xgboost"]
    results: dict[str, ModelTrainingResult] = {}

    for mtype in model_types:
        res = train_and_evaluate_model(
            model_type=mtype,
            train_records=train_records,
            val_records=val_records,
            test_records=test_records,
        )
        if run_holdout:
            try:
                holdout_m = evaluate_scenario_holdout(model_type=mtype)
                res.scenario_holdout_metrics = holdout_m
            except Exception as e:
                logger.warning(f"Scenario holdout evaluation failed for {mtype}: {e}")

        results[mtype] = res

    return results


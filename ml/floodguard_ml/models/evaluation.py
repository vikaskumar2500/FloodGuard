"""Evaluation metrics and validation-only threshold tuning."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


@dataclass
class ConfusionMatrix:
    tp: int
    fp: int
    tn: int
    fn: int


@dataclass
class ModelMetrics:
    precision: float
    recall: float
    f1: float
    roc_auc: float
    pr_auc: float
    accuracy: float
    balanced_accuracy: float
    brier_score: float
    confusion_matrix: dict[str, int]
    threshold: float
    total_samples: int
    positive_samples: int
    negative_samples: int
    provenance_warning: str = "SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy."


def evaluate_predictions(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
) -> ModelMetrics:
    """Calculate comprehensive evaluation metrics for binary predictions.

    Args:
        y_true: Ground truth binary array (0 or 1).
        y_prob: Predicted positive class probabilities in [0.0, 1.0].
        threshold: Decision cutoff threshold.
    """
    y_pred = (y_prob >= threshold).astype(np.int64)

    # Confusion matrix
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    # Calculate metrics with zero_division protection for edge cases
    prec = precision_score(y_true, y_pred, zero_division=0)
    rec = recall_score(y_true, y_pred, zero_division=0)
    f1 = f1_score(y_true, y_pred, zero_division=0)
    acc = accuracy_score(y_true, y_pred)
    bal_acc = balanced_accuracy_score(y_true, y_pred)
    brier = brier_score_loss(y_true, y_prob)

    # ROC-AUC and PR-AUC require at least one positive and one negative sample
    if len(np.unique(y_true)) > 1:
        roc = roc_auc_score(y_true, y_prob)
        pr_auc = average_precision_score(y_true, y_prob)
    else:
        roc = 0.5
        pr_auc = 0.0

    return ModelMetrics(
        precision=round(float(prec), 4),
        recall=round(float(rec), 4),
        f1=round(float(f1), 4),
        roc_auc=round(float(roc), 4),
        pr_auc=round(float(pr_auc), 4),
        accuracy=round(float(acc), 4),
        balanced_accuracy=round(float(bal_acc), 4),
        brier_score=round(float(brier), 4),
        confusion_matrix={"TP": int(tp), "FP": int(fp), "TN": int(tn), "FN": int(fn)},
        threshold=round(float(threshold), 3),
        total_samples=len(y_true),
        positive_samples=int(np.sum(y_true == 1)),
        negative_samples=int(np.sum(y_true == 0)),
    )


def select_optimal_threshold(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    candidate_thresholds: tuple[float, ...] = (0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8),
    min_recall: float = 0.70,
) -> tuple[float, list[dict[str, Any]]]:
    """Find the optimal probability threshold on the VALIDATION set.

    Policy:
    Select the threshold that maximizes F1 while achieving at least min_recall
    (if feasible), otherwise fall back to pure F1 maximization.
    """
    analysis: list[dict[str, Any]] = []
    best_threshold = 0.5
    best_f1 = -1.0
    best_f1_with_recall = -1.0
    threshold_with_recall: float | None = None

    for th in candidate_thresholds:
        metrics = evaluate_predictions(y_true, y_prob, threshold=th)
        rec = metrics.recall
        f1 = metrics.f1
        prec = metrics.precision

        analysis.append({
            "threshold": th,
            "precision": prec,
            "recall": rec,
            "f1": f1,
            "balanced_accuracy": metrics.balanced_accuracy,
        })

        if f1 > best_f1:
            best_f1 = f1
            best_threshold = th

        if rec >= min_recall and f1 > best_f1_with_recall:
            best_f1_with_recall = f1
            threshold_with_recall = th

    # Use recall-constrained threshold if available, otherwise pure F1 max
    selected = threshold_with_recall if threshold_with_recall is not None else best_threshold
    return selected, analysis


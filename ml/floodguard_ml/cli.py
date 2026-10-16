"""FloodGuard ML Pipeline & Model Training CLI.

Commands:
- build-synthetic: Build training dataset from deterministic simulation scenarios.
- build-dataset: Build training dataset from real historical observations (if DB available).
- inspect-dataset: Inspect dataset metadata and data quality report.
- train: Train a single model (baseline, logistic, or xgboost), tune threshold, and save artifacts.
- compare-models: Train and benchmark all baseline and ML models side-by-side.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from floodguard_ml.config.feature_config import FeatureConfig
from floodguard_ml.datasets.builder import DatasetBuilder
from floodguard_ml.datasets.sources import DatabaseSource, SimulationSource
from floodguard_ml.datasets.splits import time_based_split
from floodguard_ml.io.artifacts import save_dataset_artifacts
from floodguard_ml.io.readers import read_json, read_parquet
from floodguard_ml.io.writers import write_json
from floodguard_ml.models.artifacts import save_model_artifacts
from floodguard_ml.models.training import (
    train_and_compare_all_models,
    train_and_evaluate_model,
)


def build_synthetic_cmd(args: argparse.Namespace) -> int:
    """Build synthetic ML dataset using Phase 7 simulation scenarios."""
    scenarios = tuple(s.strip().upper() for s in args.scenarios.split(",") if s.strip())

    config = FeatureConfig(
        prediction_horizon_minutes=args.horizon_minutes,
        sampling_interval_minutes=args.interval_minutes,
    )

    print(f"=== FloodGuard ML: Building Synthetic Dataset ===")
    print(f"Scenarios:        {scenarios}")
    print(f"Seed:             {args.seed}")
    print(f"Horizon:          {config.prediction_horizon_minutes} minutes")
    print(f"Sampling Step:    {config.sampling_interval_minutes} minutes")
    print(f"Output Directory: {args.output}")

    source = SimulationSource(scenarios=scenarios, seed=args.seed)
    builder = DatasetBuilder(config=config)

    records = builder.build_records(source)
    print(f"Generated {len(records)} candidate records across edges and timestamps.")

    if not records:
        print("Error: No records generated.", file=sys.stderr)
        return 1

    splits = time_based_split(
        records,
        train_ratio=config.split_train_ratio,
        val_ratio=config.split_val_ratio,
        test_ratio=config.split_test_ratio,
    )

    result = save_dataset_artifacts(
        records=records,
        splits=splits,
        config=config,
        output_dir=args.output,
        source_type="SYNTHETIC",
        source_identifiers=list(scenarios),
    )

    print(f"\nDataset build successful!")
    print(f"Dataset Version:  {result.dataset_version}")
    print(f"Content Hash:     {result.dataset_content_hash[:16]}...")
    print(f"Total Rows:       {result.total_rows}")
    print(f"Train / Val / Test: {result.train_rows} / {result.val_rows} / {result.test_rows}")
    print(f"Positive Count:   {result.positive_count} ({result.positive_rate * 100:.1f}%)")
    print(f"Metadata:         {result.metadata_path}")
    print(f"Quality Report:   {result.quality_report_path}")
    return 0


def build_real_cmd(args: argparse.Namespace) -> int:
    """Build dataset from real historical PostGIS data."""
    print("=== FloodGuard ML: Building Real Historical Dataset ===")
    source = DatabaseSource()
    if not source.is_available():
        print("Real historical dataset build is currently BLOCKED: PostGIS database is not available locally.", file=sys.stderr)
        return 1
    return 0


def inspect_dataset_cmd(args: argparse.Namespace) -> int:
    """Inspect existing dataset directory."""
    dir_path = Path(args.path)
    meta_path = dir_path / "metadata.json"
    if not meta_path.exists():
        print(f"Error: metadata.json not found in {dir_path}", file=sys.stderr)
        return 1

    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    print(f"=== FloodGuard Dataset: {meta.get('dataset_version')} ===")
    print(f"Source Type:     {meta.get('source_type')}")
    print(f"Content Hash:    {meta.get('dataset_content_hash')}")
    print(f"Total Rows:      {meta.get('total_rows')}")
    print(f"Prediction Horizon: {meta.get('prediction_horizon_minutes')}m")
    print(f"Class Balance:   Positives={meta['class_distribution']['positive_count']} ({meta['class_distribution']['positive_rate']*100:.2f}%)")
    print(f"Splits:")
    for split_name, s_meta in meta.get("splits", {}).items():
        print(f"  - {split_name:10s}: {s_meta['row_count']:4d} rows, Pos={s_meta['positive_count']:3d} ({s_meta['positive_rate']*100:.1f}%), Range=[{s_meta['start_time']} -> {s_meta['end_time']}]")
    return 0


def train_cmd(args: argparse.Namespace) -> int:
    """Train single model, select threshold on validation set, and save artifacts."""
    dataset_dir = Path(args.dataset)
    meta_path = dataset_dir / "metadata.json"
    train_path = dataset_dir / "train.parquet"
    val_path = dataset_dir / "validation.parquet"
    test_path = dataset_dir / "test.parquet"

    for p in (meta_path, train_path, val_path, test_path):
        if not p.exists():
            print(f"Error: required dataset file not found: {p}", file=sys.stderr)
            return 1

    ds_meta = read_json(meta_path)
    train_records = read_parquet(train_path)
    val_records = read_parquet(val_path)
    test_records = read_parquet(test_path)

    print(f"=== FloodGuard ML: Training {args.model.upper()} ===")
    print(f"Dataset Version:  {ds_meta.get('dataset_version')}")
    print(f"Data Provenance:  SYNTHETIC DATASET EVALUATION")
    print(f"Train / Val / Test rows: {len(train_records)} / {len(val_records)} / {len(test_records)}")

    res = train_and_evaluate_model(
        model_type=args.model,
        train_records=train_records,
        val_records=val_records,
        test_records=test_records,
        min_recall=args.min_recall,
    )

    model_version = f"{args.model}-v1"
    out_dir = save_model_artifacts(
        model=res.model,
        model_version=model_version,
        model_type=res.model_type,
        output_dir=args.output,
        dataset_version=ds_meta.get("dataset_version", "unknown"),
        dataset_content_hash=ds_meta.get("dataset_content_hash", "unknown"),
        hyperparameters=res.hyperparameters,
        threshold=res.selected_threshold,
        threshold_analysis=res.threshold_analysis,
        metrics={"train": res.train_metrics, "validation": res.val_metrics, "test": res.test_metrics},
        feature_importances=res.feature_importances,
    )

    print(f"\nModel training successful!")
    print(f"Artifacts saved to: {out_dir}")
    print(f"Optimal Threshold: {res.selected_threshold} (tuned on validation set)")
    print(f"\nTest Metrics (Threshold={res.selected_threshold}):")
    print(f"  Precision: {res.test_metrics.precision:.4f}")
    print(f"  Recall:    {res.test_metrics.recall:.4f}")
    print(f"  F1-Score:  {res.test_metrics.f1:.4f}")
    print(f"  ROC-AUC:   {res.test_metrics.roc_auc:.4f}")
    print(f"  PR-AUC:    {res.test_metrics.pr_auc:.4f}")
    print(f"  Brier:     {res.test_metrics.brier_score:.4f}")
    print(f"  Accuracy:  {res.test_metrics.accuracy:.4f}")
    print(f"  Confusion: TP={res.test_metrics.confusion_matrix['TP']}, FP={res.test_metrics.confusion_matrix['FP']}, TN={res.test_metrics.confusion_matrix['TN']}, FN={res.test_metrics.confusion_matrix['FN']}")
    print(f"Latency: Single-row={res.single_inference_latency_ms:.3f} ms, Batch={res.batch_inference_latency_ms:.3f} ms")

    if res.feature_importances:
        print("\nTop 5 Important Features:")
        for fi in res.feature_importances[:5]:
            print(f"  - {fi['feature']}: {fi['importance']}")

    return 0


def compare_models_cmd(args: argparse.Namespace) -> int:
    """Train, evaluate, and benchmark Baseline, Logistic Regression, and XGBoost models."""
    dataset_dir = Path(args.dataset)
    meta_path = dataset_dir / "metadata.json"
    train_path = dataset_dir / "train.parquet"
    val_path = dataset_dir / "validation.parquet"
    test_path = dataset_dir / "test.parquet"

    for p in (meta_path, train_path, val_path, test_path):
        if not p.exists():
            print(f"Error: required dataset file not found: {p}", file=sys.stderr)
            return 1

    ds_meta = read_json(meta_path)
    train_records = read_parquet(train_path)
    val_records = read_parquet(val_path)
    test_records = read_parquet(test_path)

    print(f"===========================================================")
    print(f" FloodGuard ML: Model Comparison & Benchmarking")
    print(f" Dataset: {ds_meta.get('dataset_version')}")
    print(f" Provenance: SYNTHETIC DATASET EVALUATION")
    print(f" Splits: Train={len(train_records)}, Val={len(val_records)}, Test={len(test_records)}")
    print(f"===========================================================\n")

    results = train_and_compare_all_models(
        train_records=train_records,
        val_records=val_records,
        test_records=test_records,
        run_holdout=True,
    )

    out_base = Path(args.output)
    out_base.mkdir(parents=True, exist_ok=True)

    summary_report: dict[str, Any] = {
        "dataset_version": ds_meta.get("dataset_version"),
        "provenance": "SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.",
        "models": {},
    }

    print(f"{'Model':<22} | {'Thresh':<6} | {'Test Prec':<9} | {'Test Rec':<8} | {'Test F1':<8} | {'ROC-AUC':<8} | {'PR-AUC':<8} | {'Brier':<6} | {'Latency':<8}")
    print("-" * 105)

    for mtype, res in results.items():
        m_version = f"{mtype}-v1"
        save_model_artifacts(
            model=res.model,
            model_version=m_version,
            model_type=res.model_type,
            output_dir=out_base,
            dataset_version=ds_meta.get("dataset_version", "unknown"),
            dataset_content_hash=ds_meta.get("dataset_content_hash", "unknown"),
            hyperparameters=res.hyperparameters,
            threshold=res.selected_threshold,
            threshold_analysis=res.threshold_analysis,
            metrics={"train": res.train_metrics, "validation": res.val_metrics, "test": res.test_metrics},
            feature_importances=res.feature_importances,
        )

        tm = res.test_metrics
        print(f"{res.model_name:<22} | {res.selected_threshold:<6.2f} | {tm.precision:<9.4f} | {tm.recall:<8.4f} | {tm.f1:<8.4f} | {tm.roc_auc:<8.4f} | {tm.pr_auc:<8.4f} | {tm.brier_score:<6.4f} | {res.single_inference_latency_ms:<5.2f} ms")

        summary_report["models"][mtype] = {
            "name": res.model_name,
            "threshold": res.selected_threshold,
            "test_metrics": asdict(tm),
            "val_metrics": asdict(res.val_metrics),
            "train_metrics": asdict(res.train_metrics),
            "single_latency_ms": res.single_inference_latency_ms,
            "batch_latency_ms": res.batch_inference_latency_ms,
            "scenario_holdout": asdict(res.scenario_holdout_metrics) if res.scenario_holdout_metrics else None,
            "top_features": res.feature_importances[:5] if res.feature_importances else [],
        }

    write_json(summary_report, out_base / "comparison_report.json")
    print(f"\nComparison report written to: {out_base / 'comparison_report.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="floodguard_ml", description="FloodGuard ML Pipeline & Modeling CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcommand: build-synthetic
    p_syn = subparsers.add_parser("build-synthetic", help="Build synthetic ML dataset from simulator")
    p_syn.add_argument("--scenarios", default="NORMAL,MODERATE_RAIN,SEVERE_RAIN,FLASH_FLOOD,RECOVERY", help="Comma-separated scenario names")
    p_syn.add_argument("--seed", type=int, default=42, help="Simulation random seed")
    p_syn.add_argument("--horizon-minutes", type=int, default=30, help="Future prediction horizon in minutes")
    p_syn.add_argument("--interval-minutes", type=int, default=5, help="Sampling interval in minutes")
    p_syn.add_argument("--output", default="data/processed/synthetic-v1", help="Output artifact directory")
    p_syn.set_defaults(func=build_synthetic_cmd)

    # Subcommand: build-dataset
    p_real = subparsers.add_parser("build-dataset", help="Build ML dataset from real database data")
    p_real.add_argument("--start", default=None, help="Start ISO timestamp")
    p_real.add_argument("--end", default=None, help="End ISO timestamp")
    p_real.add_argument("--horizon-minutes", type=int, default=30, help="Prediction horizon in minutes")
    p_real.add_argument("--output", default="data/processed/v1", help="Output directory")
    p_real.set_defaults(func=build_real_cmd)

    # Subcommand: inspect-dataset
    p_insp = subparsers.add_parser("inspect-dataset", help="Inspect generated dataset metadata")
    p_insp.add_argument("--path", required=True, help="Path to processed dataset directory")
    p_insp.set_defaults(func=inspect_dataset_cmd)

    # Subcommand: train
    p_trn = subparsers.add_parser("train", help="Train single model and save artifacts")
    p_trn.add_argument("--dataset", default="data/processed/synthetic-v1", help="Path to dataset directory")
    p_trn.add_argument("--model", choices=["baseline", "logistic", "xgboost"], default="xgboost", help="Model type")
    p_trn.add_argument("--output", default="ml/artifacts", help="Output directory for model artifacts")
    p_trn.add_argument("--min-recall", type=float, default=0.70, help="Min recall constraint for validation threshold tuning")
    p_trn.set_defaults(func=train_cmd)

    # Subcommand: compare-models
    p_cmp = subparsers.add_parser("compare-models", help="Train and benchmark all baseline and ML models")
    p_cmp.add_argument("--dataset", default="data/processed/synthetic-v1", help="Path to dataset directory")
    p_cmp.add_argument("--output", default="ml/artifacts", help="Output directory for model comparison artifacts")
    p_cmp.add_argument("--min-recall", type=float, default=0.70, help="Min recall constraint for validation threshold tuning")
    p_cmp.set_defaults(func=compare_models_cmd)

    def _get_store():
        import os
        from backend.app.storage.local import LocalArtifactStore
        return LocalArtifactStore(os.environ.get("STORAGE_DIR", "/tmp/floodguard_storage"))

    def publish_dataset_cmd(args):
        from ml.floodguard_ml.artifacts.repository import DatasetArtifactRepository
        import os
        store = _get_store()
        repo = DatasetArtifactRepository(store, "ml")
        with open(args.filepath, "rb") as f:
            data = f.read()
        filename = os.path.basename(args.filepath)
        manifest = repo.publish(args.name, args.version, data, filename)
        print(f"Published dataset {manifest.artifact_id}")
        return 0

    p_pub_ds = subparsers.add_parser("publish-dataset", help="Publish dataset artifact")
    p_pub_ds.add_argument("name")
    p_pub_ds.add_argument("version")
    p_pub_ds.add_argument("filepath")
    p_pub_ds.set_defaults(func=publish_dataset_cmd)

    def fetch_dataset_cmd(args):
        from ml.floodguard_ml.artifacts.repository import DatasetArtifactRepository
        store = _get_store()
        repo = DatasetArtifactRepository(store, "ml")
        data, manifest = repo.fetch(args.name, args.version, args.filename)
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"Fetched dataset {manifest.artifact_id}")
        return 0

    p_fetch_ds = subparsers.add_parser("fetch-dataset", help="Fetch dataset artifact")
    p_fetch_ds.add_argument("name")
    p_fetch_ds.add_argument("version")
    p_fetch_ds.add_argument("filename")
    p_fetch_ds.add_argument("--out", required=True)
    p_fetch_ds.set_defaults(func=fetch_dataset_cmd)

    def publish_model_cmd(args):
        from ml.floodguard_ml.artifacts.repository import ModelArtifactRepository
        import os
        store = _get_store()
        repo = ModelArtifactRepository(store, "ml")
        with open(args.filepath, "rb") as f:
            data = f.read()
        filename = os.path.basename(args.filepath)
        manifest = repo.publish(args.name, args.version, data, filename)
        print(f"Published model {manifest.artifact_id}")
        return 0

    p_pub_model = subparsers.add_parser("publish-model", help="Publish model artifact")
    p_pub_model.add_argument("name")
    p_pub_model.add_argument("version")
    p_pub_model.add_argument("filepath")
    p_pub_model.set_defaults(func=publish_model_cmd)

    def fetch_model_cmd(args):
        from ml.floodguard_ml.artifacts.repository import ModelArtifactRepository
        store = _get_store()
        repo = ModelArtifactRepository(store, "ml")
        data, manifest = repo.fetch(args.name, args.version, args.filename)
        with open(args.out, "wb") as f:
            f.write(data)
        print(f"Fetched model {manifest.artifact_id}")
        return 0

    p_fetch_model = subparsers.add_parser("fetch-model", help="Fetch model artifact")
    p_fetch_model.add_argument("name")
    p_fetch_model.add_argument("version")
    p_fetch_model.add_argument("filename")
    p_fetch_model.add_argument("--out", required=True)
    p_fetch_model.set_defaults(func=fetch_model_cmd)

    def list_datasets_cmd(args):
        store = _get_store()
        keys = store.list("ml/datasets")
        for key in keys:
            print(key)
        return 0
        
    p_list_ds = subparsers.add_parser("list-datasets", help="List datasets")
    p_list_ds.set_defaults(func=list_datasets_cmd)

    def list_models_cmd(args):
        store = _get_store()
        keys = store.list("ml/models")
        for key in keys:
            print(key)
        return 0
        
    p_list_models = subparsers.add_parser("list-models", help="List models")
    p_list_models.set_defaults(func=list_models_cmd)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

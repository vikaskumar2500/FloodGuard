"""High-level artifact pipeline for saving and inspecting ML datasets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from floodguard_ml.config.feature_config import FeatureConfig
from floodguard_ml.datasets.splits import DatasetSplits
from floodguard_ml.datasets.validation import QualityReport, validate_dataset
from floodguard_ml.features.schema import FEATURE_SCHEMA_V1
from floodguard_ml.io.readers import read_json, read_parquet
from floodguard_ml.io.writers import compute_content_hash, write_json, write_parquet


@dataclass
class DatasetArtifactResult:
    dataset_version: str
    dataset_content_hash: str
    output_dir: Path
    total_rows: int
    train_rows: int
    val_rows: int
    test_rows: int
    positive_count: int
    positive_rate: float
    metadata_path: Path
    quality_report_path: Path


def save_dataset_artifacts(
    records: list[dict[str, Any]],
    splits: DatasetSplits,
    config: FeatureConfig,
    output_dir: str | Path,
    source_type: str,
    source_identifiers: list[str],
) -> DatasetArtifactResult:
    """Validate, split, and persist Parquet files, metadata.json, and quality_report.json."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 1. Run full validation and compute quality report
    quality_report: QualityReport = validate_dataset(records)

    # 2. Content hash and dataset version
    content_hash = compute_content_hash(records)
    config_hash = config.compute_config_hash()
    dataset_version = f"{config.feature_version}-{config_hash[:8]}-{content_hash[:8]}"

    # 3. Write Parquet split files
    write_parquet(splits.train_records, out / "train.parquet")
    write_parquet(splits.val_records, out / "validation.parquet")
    write_parquet(splits.test_records, out / "test.parquet")

    # 4. Build and write metadata.json
    metadata = {
        "dataset_version": dataset_version,
        "dataset_content_hash": content_hash,
        "feature_version": config.feature_version,
        "feature_config_hash": config_hash,
        "source_type": source_type,
        "source_identifiers": source_identifiers,
        "prediction_horizon_minutes": config.prediction_horizon_minutes,
        "sampling_interval_minutes": config.sampling_interval_minutes,
        "total_rows": len(records),
        "class_distribution": {
            "positive_count": quality_report.positive_count,
            "negative_count": quality_report.negative_count,
            "positive_rate": quality_report.positive_rate,
        },
        "splits": {
            k: asdict(v) for k, v in splits.metadata.items()
        },
        "feature_config": config.model_dump(),
        "schema": FEATURE_SCHEMA_V1.to_dict(),
        "created_at_utc": datetime.now(tz=timezone.utc).isoformat(),
    }
    metadata_path = out / "metadata.json"
    write_json(metadata, metadata_path)

    # 5. Write quality_report.json
    quality_report_path = out / "quality_report.json"
    write_json(asdict(quality_report), quality_report_path)

    return DatasetArtifactResult(
        dataset_version=dataset_version,
        dataset_content_hash=content_hash,
        output_dir=out,
        total_rows=len(records),
        train_rows=len(splits.train_records),
        val_rows=len(splits.val_records),
        test_rows=len(splits.test_records),
        positive_count=quality_report.positive_count,
        positive_rate=quality_report.positive_rate,
        metadata_path=metadata_path,
        quality_report_path=quality_report_path,
    )


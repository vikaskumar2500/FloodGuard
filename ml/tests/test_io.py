"""Unit tests for Parquet and artifact I/O."""

from __future__ import annotations

import tempfile
from pathlib import Path

from floodguard_ml.config.feature_config import FeatureConfig
from floodguard_ml.datasets.splits import time_based_split
from floodguard_ml.io.artifacts import save_dataset_artifacts
from floodguard_ml.io.readers import read_json, read_parquet
from floodguard_ml.io.writers import write_parquet
from tests.test_validation import _make_valid_row


class TestIO:
    def test_parquet_round_trip_preserves_none_and_zero(self) -> None:
        row1 = _make_valid_row("e1", "2026-10-08T12:00:00Z")
        row1["rainfall_rate_now_mm_h"] = 0.0  # explicit zero

        row2 = _make_valid_row("e2", "2026-10-08T12:00:00Z")
        row2["rainfall_rate_now_mm_h"] = None  # missing

        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "test.parquet"
            write_parquet([row1, row2], file_path)

            loaded = read_parquet(file_path)
            assert len(loaded) == 2

            assert loaded[0]["rainfall_rate_now_mm_h"] == 0.0
            assert loaded[0]["rainfall_rate_now_mm_h"] is not None

            assert loaded[1]["rainfall_rate_now_mm_h"] is None

    def test_save_dataset_artifacts_writes_all_files(self) -> None:
        rows = [
            _make_valid_row("e1", "2026-10-08T10:00:00Z"),
            _make_valid_row("e1", "2026-10-08T11:00:00Z"),
            _make_valid_row("e1", "2026-10-08T12:00:00Z"),
        ]
        config = FeatureConfig()
        splits = time_based_split(rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            res = save_dataset_artifacts(
                records=rows,
                splits=splits,
                config=config,
                output_dir=tmpdir,
                source_type="SYNTHETIC",
                source_identifiers=["test"],
            )

            assert (Path(tmpdir) / "train.parquet").exists()
            assert (Path(tmpdir) / "validation.parquet").exists()
            assert (Path(tmpdir) / "test.parquet").exists()
            assert (Path(tmpdir) / "metadata.json").exists()
            assert (Path(tmpdir) / "quality_report.json").exists()

            meta = read_json(Path(tmpdir) / "metadata.json")
            assert meta["dataset_version"] == res.dataset_version
            assert meta["total_rows"] == 3
            assert "class_distribution" in meta


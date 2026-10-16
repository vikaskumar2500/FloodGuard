"""End-to-end integration test connecting Phase 7 simulation scenarios to ML dataset generation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from floodguard_ml.config.feature_config import FeatureConfig
from floodguard_ml.datasets.builder import DatasetBuilder
from floodguard_ml.datasets.sources import SimulationSource
from floodguard_ml.datasets.splits import time_based_split
from floodguard_ml.io.artifacts import save_dataset_artifacts


class TestSimulatorPipeline:
    def test_end_to_end_synthetic_pipeline_with_positive_and_negative_labels(self) -> None:
        """Integration test: build dataset from Phase 7 scenarios.

        Must produce:
        - Deterministic records
        - Both positive and negative labels
        - Parquet and metadata artifacts
        """
        config = FeatureConfig(prediction_horizon_minutes=30, sampling_interval_minutes=5)
        source = SimulationSource(
            scenarios=("NORMAL", "FLASH_FLOOD", "RECOVERY"),
            seed=42,
        )

        builder = DatasetBuilder(config)
        records = builder.build_records(source)

        assert len(records) > 0, "No records generated from simulation scenarios"

        # Verify BOTH positive and negative samples exist
        positives = [r for r in records if r["target_flooded_within_horizon"] == 1]
        negatives = [r for r in records if r["target_flooded_within_horizon"] == 0]

        assert len(positives) > 0, "Synthetic dataset must contain positive flood examples"
        assert len(negatives) > 0, "Synthetic dataset must contain negative baseline examples"

        # Verify provenance
        assert all(r["source_type"] == "SYNTHETIC" for r in records)

        # Split and write
        splits = time_based_split(records)
        assert len(splits.train_records) > 0
        assert len(splits.val_records) > 0
        assert len(splits.test_records) > 0

        with tempfile.TemporaryDirectory() as tmpdir:
            res = save_dataset_artifacts(
                records=records,
                splits=splits,
                config=config,
                output_dir=tmpdir,
                source_type="SYNTHETIC",
                source_identifiers=["NORMAL", "FLASH_FLOOD", "RECOVERY"],
            )

            assert res.total_rows == len(records)
            assert res.positive_count == len(positives)
            assert (Path(tmpdir) / "train.parquet").stat().st_size > 0


"""Dataset and configuration determinism tests."""

from __future__ import annotations

from floodguard_ml.config.feature_config import FeatureConfig
from floodguard_ml.datasets.builder import DatasetBuilder
from floodguard_ml.datasets.sources import SimulationSource
from floodguard_ml.io.writers import compute_content_hash


class TestDeterminism:
    def test_reproducible_dataset_build_produces_identical_content_hash(self) -> None:
        """Requirement: Same raw input + same feature config -> exact same dataset content hash."""
        config = FeatureConfig(prediction_horizon_minutes=30, sampling_interval_minutes=10)

        # Build run 1
        source1 = SimulationSource(scenarios=("FLASH_FLOOD",), seed=42)
        records1 = DatasetBuilder(config).build_records(source1)
        hash1 = compute_content_hash(records1)

        # Build run 2
        source2 = SimulationSource(scenarios=("FLASH_FLOOD",), seed=42)
        records2 = DatasetBuilder(config).build_records(source2)
        hash2 = compute_content_hash(records2)

        assert hash1 == hash2
        assert len(records1) == len(records2)
        assert records1 == records2

    def test_configuration_hash_changes_with_parameters(self) -> None:
        cfg1 = FeatureConfig(prediction_horizon_minutes=30)
        cfg2 = FeatureConfig(prediction_horizon_minutes=45)
        cfg3 = FeatureConfig(prediction_horizon_minutes=30, sampling_interval_minutes=10)

        h1 = cfg1.compute_config_hash()
        h2 = cfg2.compute_config_hash()
        h3 = cfg3.compute_config_hash()

        assert h1 != h2
        assert h1 != h3
        assert h2 != h3
        # Same config gives identical hash
        assert h1 == FeatureConfig(prediction_horizon_minutes=30).compute_config_hash()


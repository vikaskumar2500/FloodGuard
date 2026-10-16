"""Unit tests for ML CLI commands."""

from __future__ import annotations

import tempfile
from pathlib import Path

from floodguard_ml.cli import main


class TestCLI:
    def test_cli_build_synthetic_and_inspect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "synth_test"

            # 1. Run build-synthetic
            code_build = main([
                "build-synthetic",
                "--scenarios", "NORMAL,FLASH_FLOOD",
                "--horizon-minutes", "30",
                "--interval-minutes", "10",
                "--output", str(out_dir),
            ])
            assert code_build == 0
            assert (out_dir / "train.parquet").exists()
            assert (out_dir / "metadata.json").exists()

            # 2. Run inspect-dataset
            code_inspect = main([
                "inspect-dataset",
                "--path", str(out_dir),
            ])
            assert code_inspect == 0

    def test_cli_build_real_reports_blocked(self) -> None:
        # DB is not running locally, so real build should return code 1 cleanly
        code_real = main([
            "build-dataset",
            "--horizon-minutes", "30",
        ])
        assert code_real == 1


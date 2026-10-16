"""Dataset artifact reader utilities."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq


def read_parquet(filepath: str | Path) -> list[dict[str, Any]]:
    """Read Parquet file and return list of row dictionaries."""
    table = pq.read_table(filepath)
    return table.to_pylist()


def read_json(filepath: str | Path) -> dict[str, Any]:
    """Read JSON file and return dict."""
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


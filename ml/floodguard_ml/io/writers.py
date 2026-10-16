"""Dataset serialization and artifact writing utilities."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from floodguard_ml.features.schema import FEATURE_COLUMNS_V1


def _build_pyarrow_schema() -> pa.Schema:
    fields = []
    type_map = {
        "string": pa.string(),
        "float64": pa.float64(),
        "int64": pa.int64(),
        "bool": pa.bool_(),
    }
    for col in FEATURE_COLUMNS_V1:
        pa_type = type_map[col.dtype]
        fields.append(pa.field(col.name, pa_type, nullable=col.nullable))
    return pa.schema(fields)


def write_parquet(records: list[dict[str, Any]], filepath: str | Path) -> None:
    """Write list of records to Parquet file using strict PyArrow schema."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    if not records:
        schema = _build_pyarrow_schema()
        table = pa.Table.from_arrays([pa.array([], type=f.type) for f in schema], schema=schema)
        pq.write_table(table, path, compression="SNAPPY")
        return

    # Extract column-oriented arrays
    arrays = []
    schema = _build_pyarrow_schema()

    for col in schema:
        col_vals = [r.get(col.name) for r in records]
        arrays.append(pa.array(col_vals, type=col.type))

    table = pa.Table.from_arrays(arrays, schema=schema)
    pq.write_table(table, path, compression="SNAPPY")


def write_json(data: Any, filepath: str | Path) -> None:
    """Write data to formatted JSON file."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def compute_content_hash(records: list[dict[str, Any]]) -> str:
    """Compute deterministic SHA-256 hash of dataset record contents.

    Sorts rows canonically by (observation_time, edge_id).
    Excludes system-volatile elements.
    """
    sorted_rows = sorted(
        records, key=lambda r: (r["observation_time"], r["edge_id"])
    )
    # Serialize to canonical JSON
    serialized = json.dumps(sorted_rows, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


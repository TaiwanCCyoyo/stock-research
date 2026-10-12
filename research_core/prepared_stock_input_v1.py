"""Bounded reads of explicit prepared stock snapshots, without live fallback."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from research_core.artifact_store import file_digest, object_digest, safe_path
from research_core.bounded_parquet import MAX_FOOTER_BYTES, read_evidence_parquet


def prepared_calendar(prepared: pd.DataFrame) -> dict[str, Any]:
    """Bind the actual supplied calendar, including invalid-price rows."""
    index = prepared.index
    if (
        not isinstance(index, pd.DatetimeIndex)
        or len(index) == 0
        or index.hasnans
        or index.tz is not None
        or not index.is_monotonic_increasing
        or not index.is_unique
    ):
        raise ValueError("prepared snapshot requires an explicit valid daily calendar")
    return {
        "sha256": object_digest([day.isoformat() for day in index]),
        "rows": len(index),
        "start": cast(pd.Timestamp, index[0]).date().isoformat(),
        "end": cast(pd.Timestamp, index[-1]).date().isoformat(),
    }


def read_prepared(path: Path, expected_digest: str | None = None) -> tuple[pd.DataFrame, str]:
    if not path.is_absolute():
        raise ValueError("absolute prepared snapshot path required")
    path = safe_path(path)
    if path.stat().st_size > 64_000_000:
        raise ValueError("prepared snapshot exceeds byte limit")
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected_digest is not None and digest != expected_digest:
        raise ValueError("prepared snapshot digest mismatch")
    # Observe footer rows/schema under the same bounds the shared reader uses.
    if len(data) < 12 or data[:4] != b"PAR1" or data[-4:] != b"PAR1":
        raise ValueError("invalid prepared Parquet framing")
    footer_bytes = struct.unpack("<I", data[-8:-4])[0]
    if footer_bytes > MAX_FOOTER_BYTES or footer_bytes > len(data) - 12:
        raise ValueError("prepared Parquet footer exceeds limit")
    footer = pq.ParquetFile(
        pa.BufferReader(data), thrift_string_size_limit=MAX_FOOTER_BYTES, thrift_container_size_limit=10_000, arrow_extensions_enabled=False
    )
    if not 0 < footer.metadata.num_rows <= 100_000 or len(footer.schema_arrow) > 64:
        raise ValueError("prepared stock rows/columns exceed limit")
    timestamps = [field.name for field in footer.schema_arrow if field.type == pa.timestamp("ns")]
    prepared = read_evidence_parquet(data, footer.metadata.num_rows, footer.schema_arrow.names, timestamp_columns=timestamps)
    if file_digest(path) != digest:
        raise ValueError("prepared snapshot changed during read")
    return prepared, digest

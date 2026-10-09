"""Preflight small portable evidence before decoding any Parquet data pages."""

from __future__ import annotations

import logging
import struct
from collections.abc import Sequence

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

LOGGER = logging.getLogger(__name__)
MAX_FOOTER_BYTES = 1_000_000
MAX_ROWS = 250_000
MAX_ROW_GROUPS = 64
MAX_EXPANDED_BYTES = 32_000_000


def read_evidence_parquet(data: bytes, expected_rows: int, columns: Sequence[str], *, timestamp_columns: Sequence[str] = ()) -> pd.DataFrame:
    """Require the exact flat schema/rows and bounded declared page sizes first.

    These are metadata preflight limits, not an OS-level memory/CPU sandbox or
    authentication of an externally supplied file.
    """
    if isinstance(expected_rows, bool) or not isinstance(expected_rows, int) or not 0 <= expected_rows <= MAX_ROWS:
        raise ValueError("Parquet expected rows exceed the evidence limit")
    if len(data) < 12 or data[:4] != b"PAR1" or data[-4:] != b"PAR1":
        raise ValueError("invalid evidence Parquet framing")
    footer_bytes = struct.unpack("<I", data[-8:-4])[0]
    if footer_bytes > MAX_FOOTER_BYTES or footer_bytes > len(data) - 12:
        raise ValueError("Parquet footer exceeds the evidence limit")
    parquet = pq.ParquetFile(
        pa.BufferReader(data),
        thrift_string_size_limit=MAX_FOOTER_BYTES,
        thrift_container_size_limit=10_000,
        arrow_extensions_enabled=False,
    )
    metadata = parquet.metadata
    if metadata.num_rows != expected_rows or metadata.num_row_groups > MAX_ROW_GROUPS:
        raise ValueError("Parquet row or row-group metadata does not match evidence limits")
    schema = parquet.schema_arrow
    if schema.names != list(columns) or metadata.num_columns != len(columns):
        raise ValueError("Parquet columns do not match the fixed evidence schema")
    if not set(timestamp_columns).issubset(columns):
        raise ValueError("timestamp allowances must name fixed evidence columns")
    for field in schema:
        if not (
            pa.types.is_null(field.type)
            or pa.types.is_boolean(field.type)
            or pa.types.is_integer(field.type)
            or pa.types.is_floating(field.type)
            or pa.types.is_string(field.type)
            or pa.types.is_large_string(field.type)
            or (field.name in timestamp_columns and field.type == pa.timestamp("ns"))
        ):
            raise ValueError("Parquet evidence requires flat primitive fields")
    expanded_bytes = 0
    for index in range(metadata.num_row_groups):
        group = metadata.row_group(index)
        if group.num_columns != len(columns) or not 0 <= group.total_byte_size <= MAX_EXPANDED_BYTES:
            raise ValueError("Parquet row-group expanded size exceeds the evidence limit")
        for column in range(group.num_columns):
            size = group.column(column).total_uncompressed_size
            if not 0 <= size <= MAX_EXPANDED_BYTES:
                raise ValueError("Parquet column expanded size exceeds the evidence limit")
            expanded_bytes += size
        if expanded_bytes > MAX_EXPANDED_BYTES:
            raise ValueError("Parquet total expanded size exceeds the evidence limit")
    LOGGER.debug("Parquet preflight rows=%d columns=%d declared_bytes=%d", expected_rows, len(columns), expanded_bytes)
    return parquet.read(use_threads=False).to_pandas()

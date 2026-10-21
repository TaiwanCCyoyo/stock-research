"""Faithful UTF8 Parquet transport for mixed numeric/absence SR-a values."""

from __future__ import annotations

import json
import logging
import math
from numbers import Real
from pathlib import Path
from typing import Any, BinaryIO, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

LOGGER = logging.getLogger(__name__)
ENCODED_COLUMNS = ("SR_a", "SR_a_value")
METADATA_KEY = b"stock-research.pattern-scan.parquet-codec"
CODEC_VERSION = "pattern-scan-mixed-sr-a.v1"


def _encode(value: Any) -> str | None:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("SR-a transport rejects booleans")
    if value is None or pd.isna(value):
        return None
    if isinstance(value, str):
        if value != "none":
            raise ValueError("SR-a transport permits only the literal absence category 'none'")
        return value
    if not isinstance(value, Real):
        raise ValueError("SR-a transport requires a numeric value, 'none' or missing")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("SR-a transport rejects nonfinite known values")
    return repr(number)


def _decode(value: Any) -> float | str | None:
    if value is None or pd.isna(value):
        return None
    if not isinstance(value, str):
        raise ValueError("encoded SR-a transport must contain nullable UTF8 strings")
    if value == "none":
        return value
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError("corrupted SR-a numerical string") from exc
    if not math.isfinite(number) or repr(number) != value:
        raise ValueError("SR-a numerical strings require canonical finite float repr")
    return number


def write_frame(frame: pd.DataFrame, stream_or_path: str | Path | BinaryIO, *, index: bool) -> None:
    """Encode only SR_a/SR_a_value; preserve all other values and pandas index.

    Known numbers use repr(float) for exact binary64 restoration, observed
    absence is 'none', unknown is Arrow null. The same nullable UTF8 field type
    is used for all-numeric, all-category and all-missing batches. Destination
    creation/exclusivity belongs to the caller, which can pass an open xb stream.
    """
    if not isinstance(frame, pd.DataFrame) or not frame.columns.is_unique:
        raise ValueError("Parquet transport requires unique DataFrame columns")
    if not isinstance(index, bool):
        raise ValueError("index must be an explicit boolean")
    encoded = frame.copy(deep=True)
    names = [name for name in ENCODED_COLUMNS if name in frame]
    for name in names:
        encoded[name] = pd.Series([_encode(value) for value in frame[name]], index=frame.index, dtype="string")
    table = pa.Table.from_pandas(encoded, preserve_index=index)
    # Explicit Arrow string avoids object/null inference or backend-dependent
    # large_string selection, including an empty or entirely missing batch.
    for name in names:
        position = table.schema.get_field_index(name)
        array = pa.array(encoded[name].tolist(), type=pa.string(), from_pandas=True)
        table = table.set_column(position, pa.field(name, pa.string(), nullable=True), array)
    metadata = dict(table.schema.metadata or {})
    metadata[METADATA_KEY] = json.dumps(
        {"version": CODEC_VERSION, "columns": names, "numeric": "repr(float), finite binary64", "absence": "none", "unknown": "null"}, sort_keys=True
    ).encode("utf-8")
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, stream_or_path, compression="zstd")
    LOGGER.debug("Wrote scan Parquet rows=%d encoded_columns=%s preserve_index=%s", len(frame), names, index)


def _declared_columns(schema: pa.Schema) -> tuple[str, ...]:
    metadata = dict(schema.metadata or {})
    if METADATA_KEY not in metadata:
        return ()
    try:
        descriptor = json.loads(metadata[METADATA_KEY])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("corrupted SR-a codec metadata") from exc
    if not isinstance(descriptor, dict) or descriptor.get("version") != CODEC_VERSION:
        raise ValueError("unsupported SR-a codec version")
    columns = descriptor.get("columns")
    if not isinstance(columns, list) or any(not isinstance(name, str) or name not in ENCODED_COLUMNS for name in columns) or len(set(columns)) != len(columns):
        raise ValueError("invalid SR-a codec column inventory")
    if set(columns) != {name for name in ENCODED_COLUMNS if name in schema.names}:
        raise ValueError("SR-a codec column inventory differs from the full Arrow schema")
    for name in columns:
        field = schema.field(name)
        if field.type != pa.string() or not field.nullable:
            raise ValueError("declared SR-a codec fields must be nullable UTF8")
    return tuple(columns)


def read_frame(path: str | Path | BinaryIO, **kwargs: Any) -> pd.DataFrame:
    """Delegate pandas columns/filters/index loading, then restore SR-a values.

    Filters on unaffected fields work unchanged. Filters directly on encoded
    SR-a fields use their documented UTF8 transport representation. Decoding
    rejects corrupt or noncanonical tokens instead of silently inventing values.
    Legacy files without codec metadata are returned unchanged, including their
    homogeneous numerical SR-a fields. Binary streams retain their original
    seek position on success and failure.
    """
    stream = None if isinstance(path, (str, Path)) else path
    original_position = None if stream is None else stream.tell()
    try:
        schema = pq.read_schema(path)
        if stream is not None and original_position is not None:
            stream.seek(original_position)
        declared = _declared_columns(schema)
        frame = pd.read_parquet(path, **kwargs)
        decoded = [name for name in declared if name in frame]
        for name in decoded:
            frame[name] = pd.Series([_decode(value) for value in cast(pd.Series, frame[name])], index=frame.index, dtype=object)
        LOGGER.debug("Read scan Parquet rows=%d decoded_columns=%s", len(frame), decoded)
        return frame
    finally:
        if stream is not None and original_position is not None:
            stream.seek(original_position)

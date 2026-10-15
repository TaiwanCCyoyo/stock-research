"""Exact binary64 restoration and stable mixed-value Arrow schemas."""

import json
import struct
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_core.pattern_scan_parquet_v1 import CODEC_VERSION, METADATA_KEY, read_frame, write_frame


def test_mixed_numeric_absence_unknown_exact_float_and_unchanged_other_columns() -> None:
    values = [0.1, -0.0, np.nextafter(0.1, 1.0), 5e-324, float.fromhex("0x1.fffffffffffffp+1023"), "none", None]
    frame = pd.DataFrame({
        "SR_a": pd.Series(values, dtype=object),
        "SR_a_value": pd.Series(values[::-1], dtype=object),
        "other_float": [np.nextafter(1.0, 2.0)] * 7,
        "other_category": ["none"] * 7,
        "other_bool": pd.Series([True, False, pd.NA, True, False, True, False], dtype="boolean"),
    })
    frame.index = pd.date_range("2020-01-01", periods=len(frame), name="Date")
    original = frame.copy(deep=True)
    stream = BytesIO()
    write_frame(frame, stream, index=True)
    stream.seek(0)
    parquet = pq.ParquetFile(stream)
    assert {
        parquet.metadata.row_group(row).column(column).compression
        for row in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(row).num_columns)
    } == {"ZSTD"}
    stream.seek(0)
    restored = read_frame(stream)
    assert restored.dtypes.equals(frame.dtypes)
    for column in ("SR_a", "SR_a_value"):
        for expected, actual in zip(frame[column], restored[column], strict=True):
            if isinstance(expected, (float, np.floating)):
                assert struct.pack("!d", float(actual)) == struct.pack("!d", float(expected))
            else:
                assert actual == expected
    pd.testing.assert_frame_equal(restored.drop(columns=["SR_a", "SR_a_value"]), frame.drop(columns=["SR_a", "SR_a_value"]), check_exact=True, check_freq=False)
    pd.testing.assert_frame_equal(frame, original, check_exact=True)
    stream.seek(0)
    metadata = json.loads(dict(pq.read_schema(stream).metadata or {})[METADATA_KEY])
    assert metadata["version"] == CODEC_VERSION and metadata["columns"] == ["SR_a", "SR_a_value"]


@pytest.mark.parametrize("values", [[0.0, 1.2], ["none", "none"], [None, pd.NA], []])
def test_numeric_category_null_and_empty_share_nullable_string_schema(values: list[Any]) -> None:
    stream = BytesIO()
    write_frame(pd.DataFrame({"SR_a": pd.Series(values, dtype=object)}), stream, index=False)
    stream.seek(0)
    field = pq.read_schema(stream).field("SR_a")
    assert field.type == pa.string() and field.nullable
    stream.seek(0)
    actual = read_frame(stream)
    assert len(actual) == len(values) and actual.SR_a.dtype == object


@pytest.mark.parametrize("value", [True, np.bool_(False), "unknown", "0.1", float("inf"), float("-inf"), object()])
def test_write_rejects_noncanonical_values(value: Any) -> None:
    with pytest.raises(ValueError):
        write_frame(pd.DataFrame({"SR_a": pd.Series([value], dtype=object)}), BytesIO(), index=False)


@pytest.mark.parametrize("token", ["bad", "nan", "inf", "-inf", "1", "0.10", " 0.1", "False"])
def test_read_rejects_corrupted_or_noncanonical_strings(token: str) -> None:
    metadata = {METADATA_KEY: json.dumps({"version": CODEC_VERSION, "columns": ["SR_a"]}).encode()}
    stream = BytesIO()
    table = pa.table({"SR_a": pa.array([token], type=pa.string())}).replace_schema_metadata(metadata)
    pq.write_table(table, stream)
    stream.seek(0)
    with pytest.raises(ValueError):
        read_frame(stream)
    assert stream.tell() == 0


def test_columns_filters_and_index_remain_usable(tmp_path: Path) -> None:
    path = tmp_path / "invented.parquet"
    frame = pd.DataFrame({"SR_a": pd.Series([0.1, "none", None], dtype=object), "horizon": [126, 252, 126], "event_id": ["a", "b", "c"]})
    frame.index = pd.Index([10, 20, 30], name="original_index")
    write_frame(frame, path, index=True)
    filtered = read_frame(path, columns=["SR_a", "event_id"], filters=[("horizon", "==", 126)])
    assert filtered.index.tolist() == [10, 30]
    assert filtered.event_id.tolist() == ["a", "c"]
    assert filtered.SR_a.tolist() == [0.1, None]
    unaffected = read_frame(path, columns=["event_id"])
    pd.testing.assert_frame_equal(unaffected, frame[["event_id"]])


def test_unencoded_transport_preserves_frame_values() -> None:
    frame = pd.DataFrame({"numeric": [0.1, -0.0], "category": ["none", None]})
    stream = BytesIO()
    write_frame(frame, stream, index=False)
    stream.seek(0)
    pd.testing.assert_frame_equal(read_frame(stream), frame, check_exact=True)


@pytest.mark.parametrize("values", [[0.1, -0.0, None], ["none", "none", None], [None, None, None]])
def test_legacy_homogeneous_sr_a_without_metadata_is_unchanged(values: list[Any]) -> None:
    source = pd.DataFrame({"SR_a": values})
    stream = BytesIO()
    source.to_parquet(stream, index=False, compression="snappy")
    stream.seek(0)
    parquet = pq.ParquetFile(stream)
    assert {
        parquet.metadata.row_group(row).column(column).compression
        for row in range(parquet.metadata.num_row_groups)
        for column in range(parquet.metadata.row_group(row).num_columns)
    } <= {"SNAPPY"}
    stream.seek(0)
    pd.testing.assert_frame_equal(read_frame(stream), source, check_exact=True)
    assert stream.tell() == 0


def test_legacy_mixed_sr_a_codec_with_snappy_remains_readable() -> None:
    metadata = {
        METADATA_KEY: json.dumps(
            {
                "version": CODEC_VERSION,
                "columns": ["SR_a"],
                "numeric": "repr(float), finite binary64",
                "absence": "none",
                "unknown": "null",
            },
            sort_keys=True,
        ).encode("utf-8")
    }
    table = pa.table({"SR_a": pa.array(["0.1", "none", None], type=pa.string())}).replace_schema_metadata(metadata)
    stream = BytesIO()
    pq.write_table(table, stream, compression="snappy")
    stream.seek(0)
    assert pq.ParquetFile(stream).metadata.row_group(0).column(0).compression == "SNAPPY"
    stream.seek(0)
    restored = read_frame(stream)
    assert restored.SR_a.dtype == object
    assert struct.pack("!d", restored.SR_a[0]) == struct.pack("!d", 0.1)
    assert restored.SR_a.tolist()[1:] == ["none", None]


@pytest.mark.parametrize(
    "descriptor",
    [
        {"version": "unsupported", "columns": ["SR_a"]},
        {"version": CODEC_VERSION, "columns": ["SR_a", "SR_a"]},
        {"version": CODEC_VERSION, "columns": ["unexpected"]},
        {"version": CODEC_VERSION, "columns": []},
    ],
)
def test_corrupted_codec_metadata_rejected_even_for_projected_columns(descriptor: dict[str, Any]) -> None:
    table = pa.table({"SR_a": pa.array(["0.1"], type=pa.string()), "other": [10]})
    table = table.replace_schema_metadata({METADATA_KEY: json.dumps(descriptor).encode()})
    stream = BytesIO()
    pq.write_table(table, stream)
    stream.seek(7)
    with pytest.raises(ValueError):
        read_frame(stream, columns=["other"])
    assert stream.tell() == 7

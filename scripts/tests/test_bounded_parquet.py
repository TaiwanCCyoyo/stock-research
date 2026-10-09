"""Tiny portable-evidence preflight tests; never read market artifacts."""

from __future__ import annotations

import io
import struct
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_core import bounded_parquet as reader


def _bytes(frame: pd.DataFrame) -> bytes:
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False)
    return stream.getvalue()


def test_small_fixed_projection_reads_with_pandas_dtypes() -> None:
    frame = pd.DataFrame({"security_id": ["A", "B"], "eligible": [True, False]})
    actual = reader.read_evidence_parquet(_bytes(frame), 2, frame.columns.tolist())
    pd.testing.assert_frame_equal(actual, frame)


@pytest.mark.parametrize("boundary", ["rows", "columns", "expanded", "row-groups"])
def test_metadata_failure_precedes_materialization(monkeypatch: pytest.MonkeyPatch, boundary: str) -> None:
    data = _bytes(pd.DataFrame({"a": [1, 2]}))
    original = pq.ParquetFile
    calls: list[dict[str, Any]] = []

    class Probe:
        def __init__(self, source: Any, **kwargs: Any) -> None:
            calls.append(kwargs)
            parsed = original(source, **kwargs)
            self.metadata = parsed.metadata
            self.schema_arrow = parsed.schema_arrow

        def read(self, **_kwargs: Any) -> Any:
            raise AssertionError("invalid metadata must reject before page decoding")

    monkeypatch.setattr(reader.pq, "ParquetFile", Probe)
    rows, columns = 2, ["a"]
    if boundary == "rows":
        rows = 3
    elif boundary == "columns":
        columns = ["unexpected"]
    elif boundary == "expanded":
        monkeypatch.setattr(reader, "MAX_EXPANDED_BYTES", 1)
    else:
        monkeypatch.setattr(reader, "MAX_ROW_GROUPS", 0)
    with pytest.raises(ValueError, match="Parquet"):
        reader.read_evidence_parquet(data, rows, columns)
    assert calls[0]["thrift_string_size_limit"] == reader.MAX_FOOTER_BYTES
    assert calls[0]["thrift_container_size_limit"] == 10_000
    assert calls[0]["arrow_extensions_enabled"] is False


def test_oversized_footer_rejects_before_thrift_parser(monkeypatch: pytest.MonkeyPatch) -> None:
    data = b"PAR1" + b"not-a-footer" + struct.pack("<I", reader.MAX_FOOTER_BYTES + 1) + b"PAR1"

    def forbidden_parser(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("oversized footer must reject before the Thrift parser")

    monkeypatch.setattr(reader.pq, "ParquetFile", forbidden_parser)
    with pytest.raises(ValueError, match="footer exceeds"):
        reader.read_evidence_parquet(data, 1, ["a"])


def test_nested_schema_rejects_before_page_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.BytesIO()
    pq.write_table(pa.table({"a": [[1], [2]]}), stream)
    with pytest.raises(ValueError, match="fixed evidence schema|flat primitive"):
        reader.read_evidence_parquet(stream.getvalue(), 2, ["a"])


@pytest.mark.parametrize("rows", [-1, True, 250_001])
def test_untrusted_expected_count_is_bounded(rows: Any) -> None:
    with pytest.raises(ValueError, match="expected rows"):
        reader.read_evidence_parquet(b"", rows, ["a"])

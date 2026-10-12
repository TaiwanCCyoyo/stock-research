"""Invented snapshots exercise bounded prepared-input reads and byte pins."""

import hashlib
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from research_core import prepared_stock_input_v1 as prepared


def write_snapshot(path: Path, table: pa.Table) -> str:
    pq.write_table(table, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_prepared_preserves_invented_values_timestamps_and_digest(tmp_path: Path) -> None:
    path = tmp_path / "invented.parquet"
    table = pa.table({
        "date": pa.array(pd.to_datetime(["2020-01-01", "2020-01-02"]), type=pa.timestamp("ns")),
        "stock_code": ["0050", "0050"],
        "value": [1.5, None],
        "valid": [True, False],
    })
    digest = write_snapshot(path, table)
    result, observed = prepared.read_prepared(path, digest)
    pd.testing.assert_frame_equal(result, table.to_pandas())
    assert observed == digest
    unpinned, unpinned_digest = prepared.read_prepared(path)
    pd.testing.assert_frame_equal(unpinned, result)
    assert unpinned_digest == digest


def test_digest_mismatch_fails_before_parquet_decoding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "invented.parquet"
    path.write_bytes(b"not even parquet")

    def unexpected_decode(*args: Any, **kwargs: Any) -> None:
        pytest.fail("digest mismatch must fail before decoding")

    monkeypatch.setattr(prepared.pq, "ParquetFile", unexpected_decode)
    with pytest.raises(ValueError, match="snapshot digest mismatch"):
        prepared.read_prepared(path, "0" * 64)


def test_relative_snapshot_path_is_rejected_even_when_it_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "invented.parquet"
    write_snapshot(path, pa.table({"value": [1]}))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute prepared snapshot path"):
        prepared.read_prepared(Path(path.name))


def test_snapshot_byte_limit_is_checked_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "invented.parquet"
    path.write_bytes(b"small fixture reporting an oversized input")
    original_stat = Path.stat

    def oversized_stat(candidate: Path, *args: Any, **kwargs: Any) -> Any:
        if candidate == path:
            return SimpleNamespace(st_size=64_000_001, st_mode=original_stat(candidate).st_mode)
        return original_stat(candidate, *args, **kwargs)

    def unexpected_read(candidate: Path) -> bytes:
        pytest.fail("oversized snapshot must fail before reading bytes")

    monkeypatch.setattr(Path, "stat", oversized_stat)
    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    with pytest.raises(ValueError, match="snapshot exceeds byte limit"):
        prepared.read_prepared(path)


@pytest.mark.parametrize("data", [b"", b"PAR1", b"NOPE" + b"\x00" * 4 + b"PAR1", b"PAR1" + b"\x00" * 4 + b"NOPE"])
def test_invalid_parquet_framing_is_rejected(tmp_path: Path, data: bytes) -> None:
    path = tmp_path / "invented.parquet"
    path.write_bytes(data)
    with pytest.raises(ValueError, match="invalid prepared Parquet framing"):
        prepared.read_prepared(path)


@pytest.mark.parametrize("footer_size", [1, prepared.MAX_FOOTER_BYTES + 1])
def test_footer_limits_are_checked_before_metadata_decode(tmp_path: Path, footer_size: int, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "invented.parquet"
    path.write_bytes(b"PAR1" + struct.pack("<I", footer_size) + b"PAR1")

    def unexpected_decode(*args: Any, **kwargs: Any) -> None:
        pytest.fail("oversized footer must fail before decoding")

    monkeypatch.setattr(prepared.pq, "ParquetFile", unexpected_decode)
    with pytest.raises(ValueError, match="footer exceeds limit"):
        prepared.read_prepared(path)


@pytest.mark.parametrize("rows,columns", [(0, 1), (100_001, 1), (1, 65)])
def test_rows_and_columns_are_bounded_before_data_pages_decode(tmp_path: Path, rows: int, columns: int, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "invented.parquet"
    table = pa.table({f"value_{index}": pa.array([1] * rows, type=pa.int64()) for index in range(columns)})
    write_snapshot(path, table)

    def unexpected_read(*args: Any, **kwargs: Any) -> None:
        pytest.fail("row/column limits must fail before data pages decode")

    monkeypatch.setattr(prepared, "read_evidence_parquet", unexpected_read)
    with pytest.raises(ValueError, match="rows/columns exceed limit"):
        prepared.read_prepared(path)


def test_nested_types_are_rejected_by_the_shared_bounded_reader(tmp_path: Path) -> None:
    path = tmp_path / "invented.parquet"
    write_snapshot(path, pa.table({"nested": [[1, 2]]}))
    with pytest.raises(ValueError, match="flat primitive fields"):
        prepared.read_prepared(path)


def test_snapshot_mutation_during_decode_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "invented.parquet"
    digest = write_snapshot(path, pa.table({"value": [1, 2]}))
    read = prepared.read_evidence_parquet

    def mutate_after_decode(*args: Any, **kwargs: Any) -> pd.DataFrame:
        result = read(*args, **kwargs)
        path.write_bytes(path.read_bytes() + b"changed")
        return result

    monkeypatch.setattr(prepared, "read_evidence_parquet", mutate_after_decode)
    with pytest.raises(ValueError, match="snapshot changed during read"):
        prepared.read_prepared(path, digest)

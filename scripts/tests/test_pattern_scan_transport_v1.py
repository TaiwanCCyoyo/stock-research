"""Synthetic full aggregate transport, consumed-byte integrity and publication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import research_core.pattern_scan_transport_v1 as transport
from research_core.hhhl_variants_query import CHUNK_BYTES
from research_core.pattern_scan_parquet_v1 import write_frame


def _source(tmp_path: Path, frame: pd.DataFrame, name: str = "source.parquet") -> Path:
    path = tmp_path / name
    write_frame(frame, path, index=True)
    return path


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "cohort_id": ["positive", "zero", "negative", "unknown"],
        "known_n": pd.Series([10, 0, 20, 0], dtype="Int64"),
        "difference": [0.2, 0.0, -0.3, np.nan],
        "SR_a": pd.Series([0.12345678901234567, "none", -0.2, None], dtype=object),
    })


def _publish(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    source = _source(tmp_path, _frame())
    output = tmp_path / "publication"
    receipt = transport.export_aggregates(output, {"q1/full.parquet": source}, source_id="source.v1", input_id="input.v1")
    return source, output, receipt


def test_full_rows_codec_raw_bytes_all_tables_and_verified_reuse(tmp_path: Path) -> None:
    source, output, receipt = _publish(tmp_path)
    frame = transport.read_aggregate(output, "q1/full.parquet")
    pd.testing.assert_frame_equal(frame, _frame())
    descriptor = receipt["tables"]["q1/full.parquet"]
    assert descriptor["rows"] == 4
    assert descriptor["bytes"] == source.stat().st_size
    assert descriptor["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    before = {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    assert transport.export_aggregates(output, {"q1/full.parquet": source}, source_id="source.v1", input_id="input.v1") == receipt
    assert before == {path.relative_to(output).as_posix(): path.read_bytes() for path in output.rglob("*") if path.is_file()}
    empty = _source(tmp_path, _frame().iloc[:0], "empty.parquet")
    second = tmp_path / "all-tables"
    receipt = transport.export_aggregates(second, {"q1/full.parquet": source, "q2/zero.parquet": empty}, source_id="source.v1", input_id="input.v1")
    assert set(receipt["tables"]) == {"q1/full.parquet", "q2/zero.parquet"}
    pd.testing.assert_frame_equal(transport.read_aggregate(second, "q2/zero.parquet"), _frame().iloc[:0])
    source.unlink()
    pd.testing.assert_frame_equal(transport.read_aggregate(output, "q1/full.parquet"), _frame())


def test_split_multiple_chunks_reconstructs_exact_full_frame(tmp_path: Path) -> None:
    frame = pd.DataFrame({"count": np.random.default_rng(20261013).integers(0, 2**63, size=100_000, dtype=np.int64)})
    source = _source(tmp_path, frame)
    assert source.stat().st_size > CHUNK_BYTES
    output = tmp_path / "publication"
    receipt = transport.export_aggregates(output, {"q6/all.parquet": source}, source_id="source.v1", input_id="input.v1")
    chunks = receipt["tables"]["q6/all.parquet"]["chunks"]
    assert len(chunks) > 1
    assert all(entry["bytes"] <= CHUNK_BYTES for entry in chunks)
    pd.testing.assert_frame_equal(transport.read_aggregate(output, "q6/all.parquet"), frame)


@pytest.mark.parametrize("damage", ("corrupt", "missing", "extra", "extra_directory", "rows", "order"))
def test_corrupt_missing_extra_parts_and_invalid_manifest_rejected(tmp_path: Path, damage: str) -> None:
    source, output, receipt = _publish(tmp_path)
    directory = output / "tables/q1/full.parquet"
    chunk = directory / receipt["tables"]["q1/full.parquet"]["chunks"][0]["path"]
    if damage == "corrupt":
        data = bytearray(chunk.read_bytes())
        data[0] ^= 1
        chunk.write_bytes(data)
    elif damage == "missing":
        chunk.unlink()
    elif damage == "extra":
        (directory / "summary.parquet.part-99999.bin").write_bytes(b"extra")
    elif damage == "extra_directory":
        (directory / "unexpected").mkdir()
    else:
        if damage == "rows":
            receipt["tables"]["q1/full.parquet"]["rows"] += 1
        else:
            receipt["tables"]["q1/full.parquet"]["chunks"][0]["path"] = "summary.parquet.part-00001.bin"
        (output / "manifest.json").write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError):
        transport.read_aggregate(output, "q1/full.parquet")
    with pytest.raises(ValueError):
        transport.export_aggregates(output, {"q1/full.parquet": source}, source_id="source.v1", input_id="input.v1")


@pytest.mark.parametrize(
    "name",
    (
        "../full.parquet",
        "/full.parquet",
        "D:/full.parquet",
        "q1\\full.parquet",
        "q1//full.parquet",
        "q1/./full.parquet",
        "full.csv",
        "CON.parquet",
        "q1/NUL/full.parquet",
        "q1/unsafe /full.parquet",
        "q1/a?.parquet",
        "q1/a\x00.parquet",
        "q1/LPT1.parquet",
        "COM¹.parquet",
        "CONOUT$.parquet",
        "CON .parquet",
        "raw-events.parquet",
        "observations.parquet",
        "q1/audits.parquet",
        "raw_events.parquet",
        "prices.parquet",
        "indicators.parquet",
        "base_labels.parquet",
        "holding_context.parquet",
        "private/full.parquet",
        "anchors.parquet",
    ),
)
def test_unsafe_or_private_logical_names_rejected(tmp_path: Path, name: str) -> None:
    source = _source(tmp_path, _frame())
    with pytest.raises(ValueError):
        transport.export_aggregates(tmp_path / "publication", {name: source}, source_id="source.v1", input_id="input.v1")
    assert not (tmp_path / "publication").exists()


@pytest.mark.parametrize("change", ("source", "input", "bytes", "allowlist"))
def test_existing_output_cannot_be_overwritten_by_different_identity(tmp_path: Path, change: str) -> None:
    source, output, _ = _publish(tmp_path)
    manifest = (output / "manifest.json").read_bytes()
    source_id, input_id = "source.v1", "input.v1"
    tables = {"q1/full.parquet": source}
    if change == "source":
        source_id = "source.v2"
    elif change == "input":
        input_id = "input.v2"
    elif change == "bytes":
        changed = _frame()
        changed.loc[0, "difference"] = -0.9
        write_frame(changed, source, index=True)
    else:
        tables["q2/extra.parquet"] = source
    with pytest.raises(ValueError, match="identity/content differs"):
        transport.export_aggregates(output, tables, source_id=source_id, input_id=input_id)
    assert (output / "manifest.json").read_bytes() == manifest
    pd.testing.assert_frame_equal(transport.read_aggregate(output, "q1/full.parquet"), _frame())


def test_interrupted_publication_retains_staging_and_retry_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path, _frame())
    output = tmp_path / "publication"
    original = transport.publish_noreplace

    def interrupt(staging: Path, destination: Path) -> None:
        assert staging.is_dir() and destination == output
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(transport, "publish_noreplace", interrupt)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        transport.export_aggregates(output, {"q1/full.parquet": source}, source_id="source.v1", input_id="input.v1")
    stages = list(tmp_path.glob(".staging-publication-*"))
    assert len(stages) == 1 and not output.exists()
    retained = {path.relative_to(stages[0]).as_posix(): path.read_bytes() for path in stages[0].rglob("*") if path.is_file()}
    monkeypatch.setattr(transport, "publish_noreplace", original)
    transport.export_aggregates(output, {"q1/full.parquet": source}, source_id="source.v1", input_id="input.v1")
    assert stages[0].is_dir()
    assert retained == {path.relative_to(stages[0]).as_posix(): path.read_bytes() for path in stages[0].rglob("*") if path.is_file()}
    pd.testing.assert_frame_equal(transport.read_aggregate(output, "q1/full.parquet"), _frame())


def test_source_change_while_capturing_fails_without_publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path, _frame())
    original = transport.file_digest
    calls = 0

    def changing_digest(path: Path) -> str:
        nonlocal calls
        calls += 1
        return original(path) if calls == 1 else "0" * 64

    monkeypatch.setattr(transport, "file_digest", changing_digest)
    with pytest.raises(ValueError, match="source changed"):
        transport.export_aggregates(tmp_path / "publication", {"q1/full.parquet": source}, source_id="source.v1", input_id="input.v1")
    assert not (tmp_path / "publication").exists()


@pytest.mark.parametrize("names", (("q1/full.parquet", "Q1/FULL.parquet"), ("q1.parquet", "q1.parquet/full.parquet")))
def test_windows_alias_and_overlapping_directories_rejected(tmp_path: Path, names: tuple[str, str]) -> None:
    source = _source(tmp_path, _frame())
    with pytest.raises(ValueError):
        transport.export_aggregates(tmp_path / "publication", dict.fromkeys(names, source), source_id="source.v1", input_id="input.v1")


def test_publication_race_preserves_existing_destination_and_staging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _source(tmp_path, _frame())
    output = tmp_path / "publication"
    original = transport.publish_noreplace

    def competing_publication(staging: Path, destination: Path) -> None:
        destination.mkdir()
        (destination / "sentinel.bin").write_bytes(b"existing publication")
        original(staging, destination)

    monkeypatch.setattr(transport, "publish_noreplace", competing_publication)
    with pytest.raises(FileExistsError):
        transport.export_aggregates(output, {"q1/full.parquet": source}, source_id="source.v1", input_id="input.v1")
    assert (output / "sentinel.bin").read_bytes() == b"existing publication"
    stages = list(tmp_path.glob(".staging-publication-*"))
    assert len(stages) == 1 and (stages[0] / "manifest.json").exists()

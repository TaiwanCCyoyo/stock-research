"""Invented stock parts exercise complete-grid barriers and shared publication."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_barrier_v1 as barrier
from research_core.artifact_store import canonical, describe_file, file_digest, write_json
from research_core.market_context import compute_context_rows
from research_core.pattern_scan_stock_v1 import StockPhase, stock_phase
from research_core.research_data_catalog import DataCatalog
from research_core.research_data_paths import DataRoots

SOURCE: dict[str, Any] = {"source_id": "synthetic-source", "runtime": {"fixture": True}}


@pytest.fixture
def supplied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[DataRoots, list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    dates = pd.bdate_range("2020-01-01", periods=80)
    results: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []

    def verify_source(source: dict[str, Any]) -> None:
        verified.append(source)
        if source != SOURCE:
            raise ValueError("synthetic source identity differs")

    monkeypatch.setattr(barrier, "verify_source", verify_source)
    for ordinal, code in enumerate(("0001", "0020")):
        close = 30.0 + ordinal + np.arange(80) * 0.1
        frame = pd.DataFrame(
            {
                "Open": close - 0.1,
                "High": close + 0.4,
                "Low": close - 0.4,
                "Close": close,
                "RawClose": close,
                "RawOpen": close - 0.1,
                "RawHigh": close + 0.4,
                "RawLow": close - 0.4,
                "VolumeLots": 1000.0,
                "Turnover": close * 1000,
                "Quality": True,
                "quality_reason": None,
            },
            index=dates,
        )
        phase = stock_phase(
            frame, security_id=f"TW:{code}", industry_ref="invented", ordinary_reference=True, definition_id=SOURCE["source_id"], input_id="synthetic-input"
        )
        # Controlled raw PAT observations in synthetic outputs, independent of
        # market detection, isolate the causal rolling barrier's behavior.
        phase.pattern_states["B1"] = 0
        phase.pattern_states.iloc[40, phase.pattern_states.columns.get_loc("B1")] = 1
        directory = primary / ".tmp" / f"stock-{code}"
        directory.mkdir(parents=True)
        artifacts = []
        rows = {}
        for field in fields(StockPhase):
            path = directory / f"{field.name}.parquet"
            table = getattr(phase, field.name)
            table.to_parquet(path)
            artifacts.append(describe_file(directory, path))
            rows[field.name] = len(table)
        receipt = {
            "complete": True,
            "code": code,
            "source_id": SOURCE["source_id"],
            "input_id": "synthetic-input",
            "output_path": str(directory),
            "artifacts": artifacts,
            "rows": rows,
        }
        write_json(directory / "receipt.json", receipt)
        results.append(receipt)
    benchmark = pd.DataFrame({"Close": 100.0 + np.arange(80), "Quality": True, "security_id": "TW:0050"}, index=dates)
    return roots, results, benchmark, verified


def test_verified_full_grid_pat_and_independent_benchmark(supplied: tuple[DataRoots, list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]]) -> None:
    roots, results, benchmark, verified = supplied
    parts = barrier.verified_parts(results, source=SOURCE, input_id="synthetic-input")
    receipt = barrier.build_barrier(parts, benchmark, roots.primary / ".tmp" / "barrier")
    assert verified == [SOURCE]
    assert receipt["stock_ids"] == ["TW:0001", "TW:0020"] and len(receipt["calendar"]) == 80
    expected_context = compute_context_rows(cast(pd.DatetimeIndex, benchmark.index).strftime("%Y-%m-%d").tolist(), benchmark.Close.tolist(), layer="past_only")
    for code, record in receipt["global_files"].items():
        frame = pd.read_parquet(record["path"])
        assert len(frame) == 80 and frame.security_id.eq(f"TW:{code}").all()
        assert frame.PAT_other_B1.iloc[39] == 0
        assert frame.PAT_other_B1.iloc[40:51].eq(1).all()
        assert frame.PAT_other_B1.iloc[51] == 0
        assert frame.MKT.tolist() == [row["state"] for row in expected_context]
    context = pd.read_parquet(roots.primary / ".tmp/barrier/context.parquet")
    assert "retrospective_state" in context and "MKT_information_cutoff" in context
    assert set(receipt["global_files"]) == {"0001", "0020"}


@pytest.mark.parametrize("damage", ("source", "input", "receipt", "payload"))
def test_source_receipt_and_bytes_fail_closed(supplied: tuple[DataRoots, list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]], damage: str) -> None:
    _, results, _, _ = supplied
    source, input_id = SOURCE, "synthetic-input"
    if damage == "source":
        source = {"source_id": "changed", "runtime": {}}
    elif damage == "input":
        input_id = "changed"
    elif damage == "receipt":
        body = {**results[0], "complete": False}
        (Path(results[0]["output_path"]) / "receipt.json").write_bytes(canonical(body))
    else:
        (Path(results[0]["output_path"]) / "common_values.parquet").write_bytes(b"corrupt invented part")
    with pytest.raises(ValueError):
        barrier.verified_parts(results, source=source, input_id=input_id)


def test_missing_stock_session_is_rejected(supplied: tuple[DataRoots, list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]]) -> None:
    roots, results, benchmark, _ = supplied
    parts = barrier.verified_parts(results, source=SOURCE, input_id="synthetic-input")
    path = parts["0001"] / "common_values.parquet"
    pd.read_parquet(path).iloc[:-1].to_parquet(path)
    with pytest.raises(ValueError):
        barrier.build_barrier(parts, benchmark, roots.primary / ".tmp" / "missing-grid")


def test_publication_reuses_versions_and_preserves_old_bytes(supplied: tuple[DataRoots, list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]]) -> None:
    roots, results, benchmark, verified = supplied
    parts = barrier.verified_parts(results, source=SOURCE, input_id="synthetic-input")
    receipt = barrier.build_barrier(parts, benchmark, roots.primary / ".tmp" / "publish-barrier")
    first = barrier.publish_stock_versions(roots, parts, receipt, source=SOURCE, input_id="synthetic-input")
    assert set(first) == {"universe", "prices", "pivots", "features", "patterns", "labels", "market"}
    catalog = DataCatalog(roots)
    retained = {path: file_digest(path) for path in (roots.primary / "research_cache").rglob("*") if path.is_file()}
    assert barrier.publish_stock_versions(roots, parts, receipt, source=SOURCE, input_id="synthetic-input") == first
    with pytest.raises(ValueError):
        barrier.publish_stock_versions(roots, parts, receipt, source=SOURCE, input_id="synthetic-input.v2")
    assert all(file_digest(path) == digest for path, digest in retained.items())
    assert len(catalog.read()["entries"]) == 7
    assert len(verified) >= 5
    for entry in first.values():
        assert entry["manifest"]["scope"] == "primary"
        assert entry["coverage"]["complete_label_period"]["start"] is None
        assert entry["coverage"]["complete_label_period"]["end"] is None


def test_barrier_exact_resume_and_legal_parquet_sidecar_tamper_rejected(
    supplied: tuple[DataRoots, list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]],
) -> None:
    roots, results, benchmark, _ = supplied
    parts = barrier.verified_parts(results, source=SOURCE, input_id="synthetic-input")
    output = roots.primary / ".tmp" / "resume-barrier"
    receipt = barrier.build_barrier(parts, benchmark, output)
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    assert barrier.build_barrier(parts, benchmark, output) == receipt
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in output.rglob("*") if path.is_file()}
    path = Path(receipt["sidecars"]["context"]["path"])
    frame = pd.read_parquet(path)
    frame["MKT"] = "mixed"
    frame.to_parquet(path)
    with pytest.raises(ValueError):
        barrier.verify_barrier(receipt)
    with pytest.raises(ValueError):
        barrier.build_barrier(parts, benchmark, output)


def test_stock_reference_seams_preserve_legacy_barrier_values_and_global_verification(
    supplied: tuple[DataRoots, list[dict[str, Any]], pd.DataFrame, list[dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    roots, results, benchmark, _ = supplied
    stock_directories = {Path(row["output_path"]) for row in results}
    original_verify, original_read = barrier.verify_stock_artifacts, barrier.read_stock_prices
    verified: list[Path] = []
    reads: list[tuple[Path, list[str] | None]] = []

    def verify_stock(directory: Path, receipt: dict[str, Any]) -> None:
        assert directory in stock_directories
        assert receipt == next(row for row in results if row["output_path"] == str(directory))
        verified.append(directory)
        original_verify(directory, receipt)

    def read_prices(directory: Path, *, columns: list[str] | None = None) -> pd.DataFrame:
        reads.append((directory, columns))
        return original_read(directory, columns=columns)

    monkeypatch.setattr(barrier, "verify_stock_artifacts", verify_stock)
    monkeypatch.setattr(barrier, "read_stock_prices", read_prices)
    parts = barrier.verified_parts(results, source=SOURCE, input_id="synthetic-input")
    receipt = barrier.build_barrier(parts, benchmark, roots.primary / ".tmp/reference-routing")
    assert reads == [(parts[code], ["Close", "quality_reason"]) for code in sorted(parts)]
    assert all(verified.count(directory) == 3 for directory in stock_directories)
    closes = pd.read_parquet(Path(receipt["sidecars"]["close_matrix"]["path"]))
    for code, directory in parts.items():
        assert closes[f"TW:{code}"].tolist() == pd.read_parquet(directory / "prices.parquet").Close.tolist()
    before = list(verified)
    barrier.verify_barrier(receipt)
    assert verified == before  # Global payloads retain their generic verifier.

"""Synthetic adapter checks for the local PR17 candidate audit."""

from __future__ import annotations

import subprocess
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_candidate_audit_v2 as kernel
from research_core import pattern_scan_local_candidate_audit_v5 as adapter
from research_core.artifact_store import file_digest, write_json
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_event_tables_v1 import EventTables
from research_core.pattern_scan_parquet_v1 import write_frame

ATOMS = (Atom("MA", "MA_b", "true"),)
CANDIDATE_ID = "synthetic-candidate"
GROUPS = ("pattern:union",)
HORIZONS = (126,)


class _Inputs:
    def __init__(self, code: str) -> None:
        self.codes: tuple[str, ...] = (code,)
        self.source_id = "synthetic-source-v1"
        self.input_id = "synthetic-input-v1"
        self.original_code: dict[str, Any] | None = {"commit": "a" * 40, "dirty": False}
        self.shared_record = {"family": "synthetic-family-v1", "generation": "g1"}
        self.bound_calls: list[tuple[str, str]] = []

    def bound(self, target: str, code: str) -> EventTables:
        self.bound_calls.append((target, code))
        return EventTables(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, {})


def _cross_check_code() -> str:
    return next(f"{number:04d}" for number in range(1, 1000) if zlib.crc32(f"{number:04d}".encode("utf-8")) % 2 == 1)


def _events(code: str) -> pd.DataFrame:
    rows = (
        ("e1", "2011-01-04", "hit", True, "known", "true", "up"),
        ("e2", "2015-01-05", "loss", True, "known", "true", "down"),
        ("e3", "2021-01-04", "unknown", False, "feature_unknown", None, "unknown"),
    )
    return pd.DataFrame([
        {
            "security_id": f"TW:{code}",
            "event_id": event_id,
            "t0": day,
            "horizon": 126,
            "pattern_id": "B1",
            "effective_label": label,
            "calendar_full": True,
            "event_main_eligible": eligible,
            "event_eligibility_excluded": False,
            "mkt": market,
            "MA_b_status": status,
            "MA_b_bin": bin_id,
        }
        for event_id, day, label, eligible, status, bin_id, market in rows
    ])


def _candidate_selection() -> dict[str, Any]:
    atom_rows = [asdict(atom) for atom in ATOMS]
    counts = {"hit": 0, "loss": 0, "flat_win": 0, "distinct_codes": 0}
    return {
        "selected_atoms": atom_rows,
        "candidates": [{"candidate_id": CANDIDATE_ID, "atoms": atom_rows, "development_counts": counts}],
        "development_counts": counts,
    }


def _source_tables(
    repo_root: Path,
    *,
    corrupt_count: bool = False,
) -> tuple[Path, Path, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conditions = repo_root / "conditions"
    conditions.mkdir(parents=True, exist_ok=True)
    write_json(conditions / "B1-selection.json", _candidate_selection())

    code = _cross_check_code()
    events = _events(code)
    rebuilt = kernel.reconstruct_candidate(
        [events],
        metadata={"pattern_id": "B1", "control_id": "pattern", "cohort_id": "union", "horizon": 126},
        candidate_id=CANDIDATE_ID,
        atoms=ATOMS,
    )
    summary, annual = rebuilt["summary"].copy(), rebuilt["annual"].copy()
    if corrupt_count:
        row = summary.index[summary.condition_status.eq("known") & summary.era.eq("all") & summary.mkt.eq("all") & summary.row_kind.eq("full")][0]
        summary.at[row, "hit_n"] += 1

    group_directory = conditions / "B1-pattern%3Aunion-h126"
    group_directory.mkdir()
    summary_path = group_directory / "B1-pattern%3Aunion-h126-summary.parquet"
    annual_path = group_directory / "B1-pattern%3Aunion-h126-annual.parquet"
    write_frame(summary, summary_path, index=False)
    write_frame(annual, annual_path, index=False)

    def result_row(path: Path) -> dict[str, Any]:
        return {
            "path": path.relative_to(repo_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": file_digest(path),
        }

    receipt = {
        "schema": "run-receipt.v1",
        "run_id": "synthetic-B1-conditions",
        "definition": "pattern-scan-local-remaining.v5",
        "parameters": {
            "target": "B1",
            "phase": "conditions",
            "original_source_id": "synthetic-source-v1",
            "original_input_id": "synthetic-input-v1",
        },
        "code": {"commit": "a" * 40, "dirty": False},
        "input_fingerprint": {"captured_at_utc": "synthetic"},
        "results": {
            "B1-selection.json": result_row(conditions / "B1-selection.json"),
            summary_path.relative_to(conditions).as_posix(): result_row(summary_path),
            annual_path.relative_to(conditions).as_posix(): result_row(annual_path),
        },
    }
    write_json(conditions / "run-receipt.json", receipt)
    return conditions, group_directory, events, summary, annual


def _prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    corrupt_count: bool = False,
) -> tuple[_Inputs, Path, Path, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=Audit Test", "-c", "user.email=audit@example.invalid", "commit", "--allow-empty", "-m", "test fixture"],
        check=True,
        capture_output=True,
    )
    conditions, _, events, source_summary, source_annual = _source_tables(tmp_path, corrupt_count=corrupt_count)
    inputs = _Inputs(_cross_check_code())
    monkeypatch.setattr(adapter, "group_frame", lambda bound, group, horizon: events.loc[events.horizon.eq(horizon)].copy())
    return inputs, conditions, tmp_path / "audit", events, source_summary, source_annual


def _run(inputs: _Inputs, conditions: Path, output: Path, repo_root: Path, **kwargs: Any) -> dict[str, Any]:
    return adapter.run_candidate_audit(
        inputs,
        conditions,
        output,
        repo_root=repo_root,
        groups=GROUPS,
        horizons=HORIZONS,
        **kwargs,
    )


def test_adapter_reconstructs_and_compares_receipted_final_tables_without_projection_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, conditions, output, events, source_summary, source_annual = _prepare(tmp_path, monkeypatch)

    result = _run(inputs, conditions, output, tmp_path, max_frame_bytes=1024 * 1024)

    expected = kernel.reconstruct_candidate(
        [events],
        metadata={"pattern_id": "B1", "control_id": "pattern", "cohort_id": "union", "horizon": 126},
        candidate_id=CANDIDATE_ID,
        atoms=ATOMS,
    )
    assert result["selected_candidate_n"] == 1
    assert result["completed_case_n"] == 1
    assert result["aggregate_checks"] == len(expected["summary"]) + len(expected["annual"])
    assert len(source_summary) == len(expected["summary"])
    assert len(source_annual) == len(expected["annual"])

    output_files = [path for path in output.rglob("*") if path.is_file()]
    assert output_files
    assert all("event" not in part.lower() for path in output_files for part in path.relative_to(output).parts)
    parquet_files = [path for path in output_files if path.suffix == ".parquet"]
    assert parquet_files
    assert all(pq.ParquetFile(path).metadata.row_group(0).column(0).compression == "ZSTD" for path in parquet_files)
    assert any(path.name == "run-receipt.json" for path in output_files)


def test_count_discrepancy_raises_without_publishing_a_passing_case(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, conditions, output, *_ = _prepare(tmp_path, monkeypatch, corrupt_count=True)

    with pytest.raises(ValueError, match="candidate|mismatch|count|audit"):
        _run(inputs, conditions, output, tmp_path, max_frame_bytes=1024 * 1024)

    assert not (output / "run-receipt.json").exists()


def test_collected_frames_are_refused_when_over_the_configured_byte_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, conditions, output, *_ = _prepare(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="frame|byte|memory|limit|audit"):
        _run(inputs, conditions, output, tmp_path, max_frame_bytes=1)

    assert not (output / "run-receipt.json").exists()


def test_completed_case_resumes_without_rebinding_original_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs, conditions, output, *_ = _prepare(tmp_path, monkeypatch)
    first = _run(inputs, conditions, output, tmp_path, max_frame_bytes=1024 * 1024)
    assert first["completed_case_n"] == 1
    bind_count = len(inputs.bound_calls)
    assert bind_count == 1

    def unexpected_group_frame(*args: Any, **kwargs: Any) -> pd.DataFrame:
        raise AssertionError("a completed final case must be reused without rebuilding its events")

    def unexpected_bound(target: str, code: str) -> EventTables:
        raise AssertionError("a completed final case must not bind original events again")

    monkeypatch.setattr(adapter, "group_frame", unexpected_group_frame)
    monkeypatch.setattr(inputs, "bound", unexpected_bound)

    resumed = _run(inputs, conditions, output, tmp_path, max_frame_bytes=1024 * 1024)

    assert resumed["completed_case_n"] == 1
    assert resumed["selected_candidate_n"] == first["selected_candidate_n"]
    assert len(inputs.bound_calls) == bind_count

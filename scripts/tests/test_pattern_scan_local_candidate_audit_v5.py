"""Synthetic adapter checks for the local PR17 candidate audit."""

from __future__ import annotations

import subprocess
import zlib
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_candidate_audit_v2 as kernel
from research_core import pattern_scan_local_candidate_audit_v5 as adapter
from research_core.artifact_store import canonical, file_digest, read_json, write_json
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


def _candidate_selection(candidate_ids: tuple[str, ...] = (CANDIDATE_ID,)) -> dict[str, Any]:
    atom_rows = [asdict(atom) for atom in ATOMS]
    counts = {"hit": 0, "loss": 0, "flat_win": 0, "distinct_codes": 0}
    return {
        "selected_atoms": atom_rows,
        "candidates": [{"candidate_id": candidate_id, "atoms": atom_rows, "development_counts": counts} for candidate_id in candidate_ids],
        "development_counts": counts,
    }


def _source_tables(
    repo_root: Path,
    *,
    corrupt_count: bool = False,
    candidate_ids: tuple[str, ...] = (CANDIDATE_ID,),
) -> tuple[Path, Path, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    conditions = repo_root / "conditions"
    conditions.mkdir(parents=True, exist_ok=True)
    write_json(conditions / "B1-selection.json", _candidate_selection(candidate_ids))

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
    candidate_ids: tuple[str, ...] = (CANDIDATE_ID,),
) -> tuple[_Inputs, Path, Path, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=Audit Test", "-c", "user.email=audit@example.invalid", "commit", "--allow-empty", "-m", "test fixture"],
        check=True,
        capture_output=True,
    )
    conditions, _, events, source_summary, source_annual = _source_tables(
        tmp_path,
        corrupt_count=corrupt_count,
        candidate_ids=candidate_ids,
    )
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


def _run_full(inputs: _Inputs, conditions: Path, output: Path, repo_root: Path) -> dict[str, Any]:
    return adapter.run_candidate_audit(
        inputs,
        conditions,
        output,
        repo_root=repo_root,
        max_frame_bytes=1024 * 1024,
    )


def _seed_completed_cases(conditions: Path, output: Path, inputs: _Inputs) -> None:
    """Create receipt-valid tiny cases so full-scope recovery skips the oracle."""
    selection = read_json(conditions / "B1-selection.json")
    candidates = adapter.select_audit_candidates({"B1": selection})
    output.mkdir(parents=True, exist_ok=True)
    for group in adapter.GROUPS:
        for horizon in (126, 252):
            for index, candidate in enumerate(candidates):
                scope = {
                    "target": "B1",
                    "candidate": candidate,
                    "group": group,
                    "horizon": horizon,
                    "original_source_id": inputs.source_id,
                    "original_input_id": inputs.input_id,
                    "stocks": list(inputs.codes),
                }
                case = {
                    "candidate_id": candidate["candidate_id"],
                    "group": group,
                    "horizon": horizon,
                    "summary_rows": 144,
                    "annual_rows": 1224,
                    "aggregate_checks": 1368,
                    "slim_frame_bytes": 1,
                }
                destination = output / f"{quote(group, safe='')}-h{horizon}-c{index + 1}"
                destination.mkdir()
                results: dict[str, dict[str, Any]] = {}
                for family in ("summary", "annual"):
                    path = destination / f"{family}.parquet"
                    with path.open("xb") as stream:
                        write_frame(pd.DataFrame({"synthetic_case": [candidate["candidate_id"]]}), stream, index=False)
                    results[path.name] = {
                        "path": str(path),
                        "bytes": path.stat().st_size,
                        "sha256": file_digest(path),
                    }
                write_json(
                    destination / "run-receipt.json",
                    {
                        "schema": "run-receipt.v1",
                        "run_id": destination.name,
                        "definition": adapter.DEFINITION,
                        "parameters": {"scope": scope, "case": case, "original_code": inputs.original_code},
                        "code": {"commit": "a" * 40, "dirty": False},
                        "input_fingerprint": {"captured_at_utc": "synthetic"},
                        "results": results,
                    },
                )


def _case_snapshot(output: Path) -> dict[str, bytes]:
    return {
        path.relative_to(output).as_posix(): path.read_bytes()
        for case_dir in output.iterdir()
        if case_dir.is_dir() and any(case_dir.name.startswith(f"{quote(group, safe='')}-h") for group in adapter.GROUPS)
        for path in case_dir.rglob("*")
        if path.is_file()
    }


def _forbid_reconstruction(monkeypatch: pytest.MonkeyPatch, inputs: _Inputs) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("verified completed cases must not bind or reconstruct events")

    monkeypatch.setattr(adapter, "reconstruct_candidate", forbidden)
    monkeypatch.setattr(adapter, "group_frame", forbidden)
    monkeypatch.setattr(inputs, "bound", forbidden)


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


def test_full_scope_completion_reentry_resolves_repo_relative_locator_without_rewriting_cases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_ids = (
        CANDIDATE_ID,
        "synthetic-candidate-b",
        "synthetic-candidate-c",
        "synthetic-candidate-d",
        "synthetic-candidate-e",
    )
    inputs, conditions, output, *_ = _prepare(tmp_path, monkeypatch, candidate_ids=candidate_ids)
    _seed_completed_cases(conditions, output, inputs)
    cases_before = _case_snapshot(output)
    _forbid_reconstruction(monkeypatch, inputs)

    first = _run_full(inputs, conditions, output, tmp_path)

    assert first["audit_complete"] is True
    assert first["selected_candidate_n"] == 5
    assert first["completed_case_n"] == 40
    assert first["aggregate_checks"] == 54720
    assert first["original_source_id"] == inputs.source_id
    assert first["original_input_id"] == inputs.input_id
    assert first["original_stock_n"] == len(inputs.codes)
    completion = output / "completion"
    summary_path = completion / "audit-summary.json"
    receipt_path = completion / "run-receipt.json"
    assert summary_path.is_file() and receipt_path.is_file()

    receipt = read_json(receipt_path)
    receipt["results"][summary_path.name]["path"] = summary_path.relative_to(tmp_path).as_posix()
    receipt_path.write_bytes(canonical(receipt))
    summary_before = summary_path.read_bytes()
    receipt_before = receipt_path.read_bytes()

    second = _run_full(inputs, conditions, output, tmp_path)

    assert second["audit_complete"] is True
    assert second["completed_case_n"] == 40
    locator = Path(read_json(receipt_path)["results"][summary_path.name]["path"])
    resolved = locator if locator.is_absolute() else tmp_path / locator
    assert resolved.resolve() == summary_path.resolve()
    assert summary_path.read_bytes() == summary_before
    assert receipt_path.read_bytes() == receipt_before
    assert _case_snapshot(output) == cases_before
    assert not inputs.bound_calls


def test_truncated_root_summary_is_preserved_while_canonical_completion_is_published(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_ids = (
        CANDIDATE_ID,
        "synthetic-candidate-b",
        "synthetic-candidate-c",
        "synthetic-candidate-d",
        "synthetic-candidate-e",
    )
    inputs, conditions, output, *_ = _prepare(tmp_path, monkeypatch, candidate_ids=candidate_ids)
    _seed_completed_cases(conditions, output, inputs)
    cases_before = _case_snapshot(output)
    legacy_summary = output / "audit-summary.json"
    legacy_bytes = b'{"audit_complete":'
    legacy_summary.write_bytes(legacy_bytes)
    _forbid_reconstruction(monkeypatch, inputs)

    result = _run_full(inputs, conditions, output, tmp_path)

    assert result["audit_complete"] is True
    assert (output / "completion" / "audit-summary.json").is_file()
    assert (output / "completion" / "run-receipt.json").is_file()
    assert legacy_summary.read_bytes() == legacy_bytes
    assert not (output / "run-receipt.json").exists()
    assert _case_snapshot(output) == cases_before
    assert not inputs.bound_calls


def test_interrupted_completion_publication_retries_without_reconstruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_ids = tuple(f"synthetic-candidate-{index}" for index in range(5))
    inputs, conditions, output, *_ = _prepare(tmp_path, monkeypatch, candidate_ids=candidate_ids)
    _seed_completed_cases(conditions, output, inputs)
    cases_before = _case_snapshot(output)
    _forbid_reconstruction(monkeypatch, inputs)
    publish = adapter.publish_noreplace

    def interrupted(source: Path, destination: Path) -> None:
        assert destination == output / "completion"
        assert (source / "audit-summary.json").is_file()
        assert (source / "run-receipt.json").is_file()
        raise RuntimeError("simulated completion publication interruption")

    monkeypatch.setattr(adapter, "publish_noreplace", interrupted)
    with pytest.raises(RuntimeError, match="publication interruption"):
        _run_full(inputs, conditions, output, tmp_path)
    assert not (output / "completion").exists()
    assert not (output / "progress.json").exists()
    assert _case_snapshot(output) == cases_before

    monkeypatch.setattr(adapter, "publish_noreplace", publish)
    result = _run_full(inputs, conditions, output, tmp_path)
    assert result["audit_complete"] is True
    assert (output / "completion" / "run-receipt.json").is_file()
    assert list(output.glob(".staging-completion-*"))
    assert _case_snapshot(output) == cases_before
    assert not inputs.bound_calls


@pytest.mark.parametrize(
    "legacy_receipt_bytes",
    (
        b'{"schema":"run-receipt.v1","definition":"partial","results":{}}',
        b'{"schema":"run-receipt.v1","results":',
    ),
)
def test_partial_or_truncated_root_receipt_is_preserved_during_completion_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_receipt_bytes: bytes,
) -> None:
    candidate_ids = (
        CANDIDATE_ID,
        "synthetic-candidate-b",
        "synthetic-candidate-c",
        "synthetic-candidate-d",
        "synthetic-candidate-e",
    )
    inputs, conditions, output, *_ = _prepare(tmp_path, monkeypatch, candidate_ids=candidate_ids)
    _seed_completed_cases(conditions, output, inputs)
    cases_before = _case_snapshot(output)
    legacy_summary = output / "audit-summary.json"
    legacy_receipt = output / "run-receipt.json"
    legacy_summary_bytes = b"legacy root summary bytes"
    legacy_summary.write_bytes(legacy_summary_bytes)
    legacy_receipt.write_bytes(legacy_receipt_bytes)
    _forbid_reconstruction(monkeypatch, inputs)

    result = _run_full(inputs, conditions, output, tmp_path)

    assert result["audit_complete"] is True
    assert (output / "completion" / "audit-summary.json").is_file()
    assert (output / "completion" / "run-receipt.json").is_file()
    assert legacy_summary.read_bytes() == legacy_summary_bytes
    assert legacy_receipt.read_bytes() == legacy_receipt_bytes
    assert _case_snapshot(output) == cases_before
    assert not inputs.bound_calls

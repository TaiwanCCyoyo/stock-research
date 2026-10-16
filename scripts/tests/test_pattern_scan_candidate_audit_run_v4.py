"""Synthetic deferred audit driver; the unchanged pure engine has separate tests."""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_candidate_audit_run_v4 as runner
from research_core import pattern_scan_result_lifecycle_v3 as lifecycle
from research_core import run_receipt
from research_core.artifact_store import canonical, describe_file, file_digest, object_digest, read_json, write_json
from research_core.research_data_paths import DataRoots


@pytest.fixture
def completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    roots = DataRoots(primary, primary / "research_data")
    run = primary / ".tmp/pattern-scan-execution/computed"
    run.mkdir(parents=True)
    task = primary / "tasks" / runner.TASK
    (task / "params").mkdir(parents=True)
    (task / "mission.md").write_text("Synthetic preregistration", encoding="utf-8")
    dates = ["2010-01-04", "2026-10-12"]
    (task / "params/input-pins-v1.json.gz").write_bytes(
        gzip.compress(
            canonical({
                "cutoff": dates[-1],
                "price_observation": {"calendar": {"dates": dates, "sha256": object_digest(dates)}},
            })
        )
    )
    source: dict[str, Any] = {"source_id": "original-source", "code": {"commit": "a" * 40, "dirty": False}}
    stock_dir = run / "parts/stock-0001"
    stock_dir.mkdir(parents=True)
    stock: dict[str, Any] = {
        "code": "0001",
        "complete": True,
        "source_id": source["source_id"],
        "input_id": "original-input",
        "request_id": "stock-request",
        "output_path": str(stock_dir),
        "artifacts": [],
    }
    write_json(stock_dir / "receipt.json", stock)
    reference = run / "phase-stock-result.json"
    write_json(reference, {"phase": "full_stock_checkpoints", "pool": {"results": [stock]}, "global_analysis_admitted": False})
    global_dir = run / "global"
    global_dir.mkdir()
    for name in ("0001", "context", "close_matrix", "jump_matrix", "benchmark"):
        pd.DataFrame({"synthetic": [1]}).to_parquet(global_dir / f"{name}.parquet", index=False)

    def global_pin(name: str) -> dict[str, str]:
        path = global_dir / f"{name}.parquet"
        return {"path": str(path), "sha256": file_digest(path)}

    barrier: dict[str, Any] = {
        "schema": "pattern-scan-barrier.v1",
        "complete": True,
        "source_id": source["source_id"],
        "input_id": "original-input",
        "calendar": dates,
        "global_files": {"0001": global_pin("0001")},
        "sidecars": {name: global_pin(name) for name in ("context", "close_matrix", "jump_matrix", "benchmark")},
        "identity": {"stock_receipts": {"0001": file_digest(stock_dir / "receipt.json")}},
        "artifacts": [describe_file(global_dir, path) for path in sorted(global_dir.glob("*.parquet"))],
    }
    write_json(global_dir / "receipt.json", barrier)
    label: dict[str, Any] = {"version_id": "checkpoint-only:labels", "manifest": {"sha256": "b" * 64}}
    pins = {"labels": {"version_id": label["version_id"], "manifest_sha256": label["manifest"]["sha256"]}}
    event_identity = {
        "code": "0001",
        "target": "R1",
        "source_id": source["source_id"],
        "input_id": "original-input",
        "shared_pins": pins,
        "global_sha256": barrier["global_files"]["0001"]["sha256"],
        "stock_request_id": stock["request_id"],
    }
    event_dir = run / "analysis/event-parts" / object_digest(event_identity)
    event_dir.mkdir(parents=True)
    for name in ("events", "conditions", "group_memberships", "daily_groups", "formula_groups"):
        pd.DataFrame({"synthetic": [1]}).to_parquet(event_dir / f"{name}.parquet", index=False)
    write_json(
        event_dir / "receipt.json",
        {
            "schema": "pattern-scan-event-part.v1",
            "complete": True,
            "identity": event_identity,
            "artifacts": [describe_file(event_dir, path) for path in sorted(event_dir.glob("*.parquet"))],
        },
    )
    event_sha = file_digest(event_dir / "receipt.json")
    retained = {}
    for group in ("pattern:union", "C-base-no-pattern", "C-base-all", "C-dip"):
        for horizon in (126, 252):
            identity = {"target": "R1", "group": group, "horizon": horizon, "ancestors": {"0001": event_sha}, "inventory": "c" * 64}
            token = object_digest(identity)
            directory = run / "analysis/summaries" / token
            directory.mkdir(parents=True)
            for kind in ("summary", "annual"):
                path = directory / f"{kind}.parquet"
                pd.DataFrame({"feature_id": ["candidate"] * 5, "candidate_id": [f"c{i}" for i in range(5)], "split": ["cross-check"] * 5}).to_parquet(
                    path, index=False
                )
                retained[f"q1-q3/{kind}/{token}.parquet"] = path
            write_json(
                directory / "receipt.json",
                {
                    "schema": "pattern-scan-summary-group.v1",
                    "complete": True,
                    "identity": identity,
                    "artifacts": [describe_file(directory, path) for path in sorted(directory.glob("*.parquet"))],
                },
            )
    selection = {
        "R1": {
            "candidates": [{"candidate_id": f"c{i}", "atoms": [{"family": "MA", "feature_id": "MA_b", "bin_id": "true", "selectable": True}]} for i in range(5)]
        }
    }
    selection_path = run / "analysis/selection.json"
    write_json(selection_path, selection)
    retained["selection.json"] = selection_path
    provenance = {
        "selection": selection,
        "label_checkpoint": label,
        "executor": {"commit": "d" * 40, "dirty": False},
        "stock_reference": {"path": str(reference), "bytes": reference.stat().st_size, "sha256": file_digest(reference)},
    }
    descriptor = lifecycle.record_computed_results(run, retained, source=source, input_id="original-input", provenance=provenance)
    calls: dict[str, list[Any]] = {"verify": [], "engine": [], "code": []}
    original_verify = runner.verify_computed_results

    def verify(value: dict[str, Any]) -> dict[str, Any]:
        calls["verify"].append(value)
        return original_verify(value)

    def execution_code(root: Path) -> dict[str, Any]:
        calls["code"].append(root)
        return {"commit": "d" * 40, "dirty": False}

    def slim(directory: Path, group: str, horizon: int) -> pd.DataFrame:
        assert directory == event_dir
        return pd.DataFrame([
            {
                "security_id": "TW:0001",
                "event_id": f"{group}:{horizon}",
                "t0": "2011-01-04",
                "horizon": horizon,
                "effective_label": "unknown",
                "calendar_full": False,
                "event_main_eligible": False,
                "event_eligibility_excluded": False,
                "mkt": "unknown",
                "MA_b_status": "known",
                "MA_b_bin": "true",
                "unused_large_column": "omit",
            }
        ])

    def reconstruct(frames: Any, *, metadata: dict[str, Any], candidate_id: str, atoms: Any) -> dict[str, pd.DataFrame]:
        frame = pd.concat(list(frames), ignore_index=True)
        assert "unused_large_column" not in frame
        group = "pattern:union" if metadata["control_id"] == "pattern" else metadata["control_id"]
        assert frame.event_id.tolist() == [f"{group}:{metadata['horizon']}"]
        calls["engine"].append((candidate_id, group, metadata["horizon"]))
        frame["membership_state"], frame["split"] = 1, "cross-check"
        aggregate = pd.DataFrame({"feature_id": ["candidate"], "candidate_id": [candidate_id], "split": ["cross-check"]})
        return {"summary": aggregate, "annual": aggregate.copy(), "memberships": frame}

    def compare(rebuilt: Any, *, stored_summary: pd.DataFrame, stored_annual: pd.DataFrame) -> dict[str, int]:
        assert stored_summary.candidate_id.tolist() == rebuilt["summary"].candidate_id.tolist()
        assert stored_annual.candidate_id.tolist() == rebuilt["annual"].candidate_id.tolist()
        return {"summary_rows": 144, "annual_rows": 1224, "aggregate_checks": 1368}

    monkeypatch.setattr(runner, "verify_computed_results", verify)
    monkeypatch.setattr(runner, "code_identity", execution_code)
    monkeypatch.setattr(run_receipt, "code_identity", execution_code)
    monkeypatch.setattr(runner, "group_frame", slim)
    monkeypatch.setattr(runner, "reconstruct_candidate", reconstruct)
    monkeypatch.setattr(runner, "compare_candidate", compare)
    monkeypatch.setattr(run_receipt, "producer_data_root", lambda *args: pytest.fail("producer read forbidden"))
    return {"roots": roots, "run": run, "descriptor": descriptor, "event_dir": event_dir, "calls": calls, "selection": selection}


def _run(case: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return runner.audit_computed_scan(case["roots"], computed_results=case["descriptor"], run_root=case["run"], output_id="audit", **kwargs)


def _update_computed(case: dict[str, Any], body: dict[str, Any]) -> None:
    path = Path(case["descriptor"]["path"])
    path.write_bytes(canonical(body))
    case["descriptor"] = {**case["descriptor"], "sha256": file_digest(path)}


def test_deferred_full_scope_no_legacy_response_or_published_pins_and_reuse(completed: dict[str, Any]) -> None:
    result = _run(completed)
    assert result["audit_complete"] is True and result["aggregate_checks"] == 54_720 and result["mismatch_n"] == 0
    assert len(completed["calls"]["engine"]) == 40 and len(completed["calls"]["verify"]) == 1
    assert result["identity"]["source"]["code"]["commit"] == "a" * 40
    assert result["audit_execution_code"]["commit"] == "d" * 40
    assert result["existing_event_audit"]["status"] == "unknown"
    assert not (completed["run"] / "response-all.json").exists()
    output = Path(result["output_path"])
    assert output == completed["run"] / "audits/candidate-reconstruction/audit"
    assert run_receipt.changed_results(output / "run-receipt.json", runner.CODE_ROOT) == []
    engine_calls = len(completed["calls"]["engine"])
    assert _run(completed) == result and len(completed["calls"]["engine"]) == engine_calls
    payload = next(output.glob("*-memberships.parquet"))
    payload.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed|mismatch"):
        _run(completed)


@pytest.mark.parametrize("mutation", ("index", "payload", "stock-reference", "event-receipt", "summary-receipt", "selection", "active"))
def test_changed_computed_or_ancestor_refused_before_engine(completed: dict[str, Any], mutation: str) -> None:
    body = read_json(Path(completed["descriptor"]["path"]))
    if mutation == "index":
        Path(completed["descriptor"]["path"]).write_bytes(b"{}")
    elif mutation == "payload":
        Path(body["artifacts"][0]["source_path"]).write_bytes(b"corrupt")
    elif mutation == "stock-reference":
        path = completed["run"] / "phase-stock-result.json"
        path.write_bytes(b"{}")
    elif mutation == "event-receipt":
        path = completed["event_dir"] / "receipt.json"
        receipt = read_json(path)
        receipt["identity"]["global_sha256"] = "0" * 64
        path.write_bytes(canonical(receipt))
    elif mutation == "summary-receipt":
        path = next(Path(row["source_path"]).parent / "receipt.json" for row in body["artifacts"] if row["path"].startswith("q1-q3/summary/"))
        receipt = read_json(path)
        receipt["identity"]["ancestors"] = {}
        path.write_bytes(canonical(receipt))
    elif mutation == "selection":
        body["provenance"]["selection"] = {}
        _update_computed(completed, body)
    else:
        write_json(completed["run"] / ".scan-active.json", {"pid": 123})
    with pytest.raises((ValueError, FileNotFoundError)):
        _run(completed)
    assert not completed["calls"]["engine"]


def test_explicit_reference_and_run_cannot_escape_ownership(completed: dict[str, Any], tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escaped"):
        _run(completed, stock_reference=tmp_path / "outside.json")
    with pytest.raises(ValueError, match="primary task scratch"):
        runner.audit_computed_scan(completed["roots"], computed_results=completed["descriptor"], run_root=tmp_path, output_id="audit")
    with pytest.raises(ValueError):
        runner.audit_computed_scan(completed["roots"], computed_results=completed["descriptor"], run_root=completed["run"], output_id="../escape")


def test_fewer_than_five_candidates_is_explicitly_incomplete(completed: dict[str, Any]) -> None:
    body = read_json(Path(completed["descriptor"]["path"]))
    selection = {"R1": {"candidates": completed["selection"]["R1"]["candidates"][:2]}}
    path = completed["run"] / "analysis/selection.json"
    path.write_bytes(canonical(selection))
    body["provenance"]["selection"] = selection
    for row in body["artifacts"]:
        if row["path"] == "selection.json":
            row.update(bytes=path.stat().st_size, sha256=file_digest(path))
    _update_computed(completed, body)
    result = _run(completed)
    assert result["selected_candidate_n"] == 2 and result["aggregate_checks"] == 2 * 4 * 2 * 1368
    assert result["audit_complete"] is False


def test_existing_ten_event_metadata_is_separate_from_candidate_reconstruction(completed: dict[str, Any]) -> None:
    body = read_json(Path(completed["descriptor"]["path"]))
    directory = completed["run"] / "analysis/audits"
    directory.mkdir()
    for name, frame in (
        ("raw_events", pd.DataFrame({"event_id": range(10)})),
        ("cold_events", pd.DataFrame({"event_id": range(10)})),
        ("conditions", pd.DataFrame({"matches": [True] * 30})),
    ):
        path = directory / f"{name}.parquet"
        frame.to_parquet(path, index=False)
        body["artifacts"].append({**describe_file(directory, path), "path": f"audits/events/{name}.parquet", "source_path": str(path), "storage": "owned"})
    _update_computed(completed, body)
    result = _run(completed)
    evidence = result["existing_event_audit"]
    assert evidence["event_audit_n"] == 10 and evidence["condition_comparisons"] == 30
    assert evidence["executed_by_candidate_driver"] is False and evidence["ten_event_scope_present"] is True
    assert result["aggregate_checks"] == 54_720


def test_interrupted_engine_keeps_staging_without_success_receipt(completed: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("synthetic engine interruption")

    monkeypatch.setattr(runner, "reconstruct_candidate", interrupted)
    with pytest.raises(RuntimeError, match="engine interruption"):
        _run(completed)
    parent = completed["run"] / "audits/candidate-reconstruction"
    assert not (parent / "audit").exists() and list(parent.glob(".staging-audit-*"))


def test_selected_event_inventory_verified_once_across_five_candidates(completed: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    original = runner.verify_files
    observed = []

    def verify(directory: Path, artifacts: Any) -> None:
        observed.append(directory)
        original(directory, artifacts)

    monkeypatch.setattr(runner, "verify_files", verify)
    _run(completed)
    # lifecycle already verified retained aggregates; only the expanded event
    # part requires another inventory here. The pure engine is still independent.
    assert observed == [completed["event_dir"]]


def test_rebase_relative_result_locator_preserves_descriptor_and_rejects_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code_root = tmp_path / "checkout"
    stage = code_root / ".tmp/stage"
    stage.mkdir(parents=True)
    result = stage / "summary.parquet"
    result.write_bytes(b"synthetic result")
    path = stage / "run-receipt.json"
    descriptor = {"path": result.relative_to(code_root).as_posix(), "bytes": result.stat().st_size, "sha256": file_digest(result)}
    write_json(path, {"results": {"summary.parquet": descriptor}})
    monkeypatch.setattr(runner, "CODE_ROOT", code_root)
    final = tmp_path / "audit"
    rebased = runner._rebase_results(path, stage, final)
    assert rebased["results"]["summary.parquet"] == {**descriptor, "path": str(final / "summary.parquet")}
    path.write_bytes(canonical({"results": {"bad": {"path": str(tmp_path / "outside")}}}))
    with pytest.raises(ValueError, match="escaped staging"):
        runner._rebase_results(path, stage, final)


def test_cli_forwards_explicit_computed_and_reference(completed: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import audit_pattern_scan_candidates as cli

    captured = {}

    def audit(roots: DataRoots, **kwargs: Any) -> dict[str, Any]:
        assert roots == completed["roots"]
        captured.update(kwargs)
        return {"audit_complete": True, "selected_candidate_n": 5, "aggregate_checks": 54_720, "output_path": "synthetic"}

    monkeypatch.setattr(cli, "audit_computed_scan", audit)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_pattern_scan_candidates",
            "--primary-root",
            str(completed["roots"].primary),
            "--data-root",
            str(completed["roots"].data),
            "--run-root",
            str(completed["run"]),
            "--computed-results",
            completed["descriptor"]["path"],
            "--stock-reference",
            str(completed["run"] / "phase-stock-result.json"),
            "--output-id",
            "audit",
        ],
    )
    cli.main()
    assert captured == {
        "computed_results": {"path": completed["descriptor"]["path"], "sha256": completed["descriptor"]["sha256"]},
        "run_root": completed["run"],
        "stock_reference": completed["run"] / "phase-stock-result.json",
        "output_id": "audit",
    }
    assert json.loads(capsys.readouterr().out)["aggregate_checks"] == 54_720

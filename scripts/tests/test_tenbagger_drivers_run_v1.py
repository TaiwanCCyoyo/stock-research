"""Execution boundaries and comparable institutional denominators, using synthetic inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research_core import momentum_only_v1 as momentum
from research_core import tenbagger_drivers_run_v1 as runner
from research_core import tenbagger_drivers_v1 as drivers


def _example_stock(code: str = "synthetic") -> drivers.DriverStock:
    labels = np.array([1, 2, 1, 2, 1, 3], dtype=np.int8)
    daily = momentum.StockDaily(
        code=code,
        split="development",
        eligible=np.array([True, True, True, False, True, True]),
        jump=np.zeros(6, dtype=bool),
        c52w=np.zeros(6, dtype=bool),
        atoms={"A1": np.array([1, 1, 1, 1, 0, 0], dtype=np.int8), "A2": np.ones(6, dtype=np.int8)},
        ret120=np.zeros(6),
        labels={label: labels.copy() for label in momentum.LABELS},
        main_eligible={label: np.ones(6, dtype=bool) for label in momentum.LABELS},
        calendar_full={horizon: np.ones(6, dtype=bool) for horizon in momentum.HORIZONS},
    )
    return drivers.DriverStock(
        daily,
        np.full(6, 100.0),
        "synthetic",
        pd.DataFrame({"HOT": np.ones(6, dtype=np.int8), "SMALL": np.ones(6, dtype=np.int8), "INST": [-1, 1, 0, 1, -1, 1]}),
    )


def test_missing_institutional_days_change_both_comparison_denominators() -> None:
    calendar = pd.date_range("2010-01-04", periods=6)
    stock = _example_stock()
    counts, cooled = drivers.formal_counts([stock], calendar)
    metric = {name: index for index, name in enumerate(momentum.METRICS)}

    def totals(group: str) -> tuple[int, int, int]:
        values = counts[drivers.GROUPS.index(group), drivers.LABELS.index((252, 3.0))].sum(axis=(0, 1))
        return int(values[metric["known_n"]]), int(values[metric["hit_n"]]), int(values[metric["loss_n"]])

    # Unknown flow days contain two winners; retaining them in an INST baseline
    # would incorrectly raise its hit rate from 1/3 to 3/5.
    assert totals("C-base-daily") == (5, 3, 1)
    assert totals("C-base-daily|INST-known") == (3, 1, 1)
    assert totals("CORE") == (3, 2, 1)
    assert totals("CORE|INST-known") == (2, 1, 1)
    # INST=0 is still known and stays in both baselines. An ineligible INST=1
    # day must not enter the condition's own numerator or denominator.
    assert totals("INST") == (2, 0, 1)
    _, _, verdicts = drivers.formal_tables(counts, cooled, [stock.daily.code], reps=4)
    inst = verdicts.loc[verdicts.group_id.eq("INST")]
    assert set(inst.baseline) == {"C-base-daily|INST-known"}
    assert inst.verdict.eq("inseparable").all()


@pytest.mark.parametrize(
    "change",
    [
        {"state": "OPEN", "mergedAt": None},
        {"mergedBy": {"login": "another-user"}},
        {"baseRefName": "other-branch"},
        {"mergeCommit": None},
    ],
)
def test_only_actual_owner_merge_into_main_satisfies_gate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, change: dict) -> None:
    record = {
        "state": "MERGED",
        "mergedAt": "2099-01-01T00:00:00Z",
        "mergedBy": {"login": runner.OWNER},
        "mergeCommit": {"oid": "merged"},
        "baseRefName": "main",
    }
    record.update(change)
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(record), ""))

    def no_ancestry(*args: object) -> str:
        pytest.fail("An invalid PR must be rejected before consulting ancestry")

    monkeypatch.setattr(runner, "_git", no_ancestry)
    with pytest.raises(ValueError, match="owner|merge commit"):
        runner.check_merged_pr(123, tmp_path)


def test_owner_merge_must_also_be_in_fetched_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    record = {
        "state": "MERGED",
        "mergedAt": "2099-01-01T00:00:00Z",
        "mergedBy": {"login": runner.OWNER},
        "mergeCommit": {"oid": "merged"},
        "baseRefName": "main",
    }
    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, json.dumps(record), ""))

    def absent_merge(repo: Path, *args: str) -> str:
        assert args == ("merge-base", "--is-ancestor", "merged", "origin/main")
        raise ValueError("Git prerequisite failed: merge absent from fetched main")

    monkeypatch.setattr(runner, "_git", absent_merge)
    with pytest.raises(ValueError, match="absent"):
        runner.check_merged_pr(123, tmp_path)


def _approved_sources(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for relative in (runner.TASK / "mission.md", *runner.SOURCES):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("approved source\n", encoding="utf-8")
    monkeypatch.setattr(runner, "check_merged_pr", lambda number, repo: {"state": "MERGED"})
    monkeypatch.setattr(runner, "_git", lambda *args: "approved source")


def test_changed_executor_is_rejected_after_merge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _approved_sources(tmp_path, monkeypatch)
    (tmp_path / runner.SOURCES[0]).write_text("unreviewed source", encoding="utf-8")
    with pytest.raises(ValueError, match="source differs"):
        runner.execution_gate(tmp_path, mission_pr=1, code_pr=2, step="retro", formal_decision=None)


def test_formal_requires_explicit_decision_and_preserved_retro_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _approved_sources(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="recorded decision"):
        runner.execution_gate(tmp_path, mission_pr=1, code_pr=2, step="formal", formal_decision=None)
    destination = tmp_path / runner.TASK / "results/retro/synthetic"
    destination.mkdir(parents=True)
    evidence = destination / "r6-recommendation.json"
    evidence.write_text(json.dumps({"rule": "R6", "owner_decision_required": True, "recommend_continue": False}), encoding="utf-8")
    receipt = destination / "run-receipt.json"
    receipt.write_text(
        json.dumps({
            "schema": "run-receipt.v1",
            "definition": drivers.DEFINITION_ID,
            "parameters": {"step": "retro"},
            "results": {
                evidence.name: {
                    "path": evidence.relative_to(tmp_path).as_posix(),
                    "bytes": evidence.stat().st_size,
                    "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
                }
            },
        }),
        encoding="utf-8",
    )
    decision = tmp_path / runner.TASK / "owner-decision.json"
    decision.write_text(
        json.dumps({"step": "formal", "decision": "continue", "decided_by": runner.OWNER, "retro_receipt": receipt.relative_to(tmp_path).as_posix()}),
        encoding="utf-8",
    )
    # The owner's decision controls continuation even when R6 does not recommend it.
    result = runner.execution_gate(tmp_path, mission_pr=1, code_pr=2, step="formal", formal_decision=decision)
    assert result["formal_decision"]["decision"] == "continue"
    evidence.write_text("changed after owner review", encoding="utf-8")
    with pytest.raises(ValueError, match="preserved retrospective results"):
        runner.execution_gate(tmp_path, mission_pr=1, code_pr=2, step="formal", formal_decision=decision)


def test_unmerged_probe_stops_before_any_producer_or_hold_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def unmerged(*args: object, **kwargs: object) -> dict:
        raise ValueError("owner merge pending")

    def no_data() -> None:
        pytest.fail("Unmerged execution must not touch producer state")

    monkeypatch.setattr(runner, "execution_gate", unmerged)
    monkeypatch.setattr(runner, "assert_institutional_idle", no_data)
    monkeypatch.setattr(runner, "current_generation", no_data)
    arguments = argparse.Namespace(mission_pr=1, code_pr=2, step="retro", formal_decision=None, probe=True)
    with pytest.raises(ValueError, match="owner merge pending"):
        runner.run(arguments)


def test_probe_checks_identical_local_outputs_without_global_parity() -> None:
    measured = runner.probe_stocks(["A", "B"], _example_stock, generation="synthetic", code_commit="synthetic")
    assert measured["global_parity"] == "not_evaluated"
    assert [row["workers"] for row in measured["measurements"]] == [1, 2, 4]
    assert all(row["identical"] for row in measured["measurements"])


def test_probe_stops_if_parallel_output_changes() -> None:
    calls = 0

    def changing(code: str) -> drivers.DriverStock:
        nonlocal calls
        calls += 1
        stock = _example_stock(code)
        if calls > 1:
            stock.daily.eligible[0] = False
        return stock

    with pytest.raises(drivers.AlignmentError, match="parallel probe differs"):
        runner.probe_stocks(["A"], changing, generation="synthetic", code_commit="synthetic")


def test_one_a4_mismatch_stops_before_later_alignment_and_formal_counts(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    checkpoints = tmp_path / "synthetic-checkpoints"
    checkpoints.mkdir()
    (checkpoints / "stocks.json").write_text(json.dumps({"codes": 1, "cutoff": momentum.CUTOFF, "generation": "synthetic"}), encoding="utf-8")
    published = tmp_path / runner.PR61_TASK / "results"
    published.mkdir(parents=True)
    (published / "research_result.json").write_text(json.dumps({"generation": "synthetic"}), encoding="utf-8")
    stock = _example_stock()
    monkeypatch.setattr(runner, "load_stock", lambda *args: stock.daily)
    monkeypatch.setattr(momentum, "h_states", lambda *args: [np.zeros(6, dtype=np.int8)])

    def no_later_work(*args: object, **kwargs: object) -> None:
        pytest.fail("A4 mismatch must stop before later alignment or formal comparisons")

    monkeypatch.setattr(runner.pd, "read_parquet", no_later_work)
    monkeypatch.setattr(drivers, "formal_counts", no_later_work)
    actual = np.array([1, 0, 0, 0, 0, 0], dtype=np.int8)
    with pytest.raises(drivers.AlignmentError, match="alignment failed"):
        runner.alignment_gate([stock], [actual], checkpoints, tmp_path, tmp_path, formal=True)
    diagnostic = json.loads((tmp_path / "alignment.json").read_text(encoding="utf-8"))
    assert diagnostic["verdict"] == "stop"
    assert diagnostic["differences"]["A4"][0]["different_cells"] == 1

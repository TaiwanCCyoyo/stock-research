"""Synthetic parity and boundary evidence; no published market artifacts are read."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from research_core import hhhl_variants_observations as original
from research_core import multiple_observations_v1 as multiple
from research_core.pattern_scan_flags_v1 import event_flag_observations
from research_core.strength_flags_run_v1 import AlignmentError, assert_observation_parity, compare_reference, require_exact_alignment, verify_owner_merges
from research_core.strength_flags_v1 import APPLICABLE_FLAGS, FLAG_STATES, BatchFlagIndex


@pytest.mark.parametrize(
    "path", [[], [10], [10, 20, None, 5], [10, None, 20, 5], [10, 20, 5, 5], [10, 15, 10, 5], [0, 20, 5], [10, np.inf, 20], [10, 20, 30, 40]]
)
@pytest.mark.parametrize("horizon", [1, 2, 3, 5])
def test_twofold_window_records_are_exact(path: list[float | None], horizon: int) -> None:
    assert asdict(multiple.classify_window(path, horizon)) == asdict(original.classify_window(path, horizon))


@pytest.mark.parametrize("path", [[10, 20, None, 5], [10, 15, 20, 5], [10, 9, 8], [10, None, 20], [10], [], [None, 10]])
@pytest.mark.parametrize("landmark", [1, 2, 3, 5])
@pytest.mark.parametrize("legacy", [False, True])
def test_twofold_riskset_records_are_exact(path: list[float | None], landmark: int, legacy: bool) -> None:
    assert asdict(multiple.landmark_riskset(path, landmark, 9, legacy_active=legacy)) == asdict(
        original.landmark_riskset(path, landmark, 9, legacy_active=legacy)
    )


def test_randomized_twofold_parity_and_target_specific_clock() -> None:
    rng = np.random.default_rng(20261024)
    for _ in range(100):
        options: list[float | None] = [None, 5.0, 10.0, 20.0, 30.0, 50.0]
        path = [options[int(index)] for index in rng.choice(len(options), size=12)]
        assert multiple.classify_window(path, 10) == original.classify_window(path, 10)
        assert multiple.landmark_riskset(path, 5) == original.landmark_riskset(path, 5, 1)
    assert multiple.landmark_riskset([10, 20, 29, 30], 2, target_multiple=3).eligible
    assert multiple.landmark_riskset([10, 20, 29, 30], 3, target_multiple=3).state == "early_hit"
    assert multiple.classify_window([10, 20, 29, 30], 3, 3).first_hit_offset == 3


@pytest.mark.parametrize("target", [True, 1, 0, -1, np.nan, np.inf])
def test_invalid_targets_rejected(target: float) -> None:
    with pytest.raises(ValueError):
        multiple.classify_window([10, 20], 1, target)


def synthetic_frame(seed: int = 19, n: int = 160) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    close = 10 * np.exp(np.cumsum(rng.normal(0.005, 0.06, n)))
    dates = pd.bdate_range("2010-01-04", periods=n)
    frame = pd.DataFrame(
        {"Close": close, "SMA20": close * rng.uniform(0.95, 1.1, n), "SMA60": close * rng.uniform(0.9, 1.1, n), "BBLower": close * rng.uniform(0.8, 1.03, n)},
        index=dates,
    )
    frame.iloc[[15, 76, 124], frame.columns.get_loc("Close")] = np.nan
    frame.iloc[40, frame.columns.get_loc("SMA20")] = np.nan
    raw = [
        ("low", 0, 3, 8.0),
        ("low", 2, 7, 9.0),
        ("low", 4, 12, 9.5),
        ("high", 0, 2, 12.0),
        ("high", 3, 6, 11.0),
        ("high", 4, 6, 10.5),
        ("high", 14, 16, 12.0),
        ("high", 18, 20, 11.0),
        ("low", 30, 50, 10.0),
        ("high", 100, 120, 30.0),
    ]
    pivots = pd.DataFrame([
        {"k": 1.5, "kind": kind, "extreme_index": e, "confirmation_index": c, "extreme_date": dates[e], "confirmed_at": dates[c], "price": price}
        for kind, e, c, price in raw
    ])
    return frame, pivots


@pytest.mark.parametrize("seed", [19, 20261024, 71])
def test_batch_matches_every_public_field_on_seeded_random_anchors(seed: int) -> None:
    frame, pivots = synthetic_frame(seed)
    t0s = sorted(set([0, 2, 6, 14, 15, 40, 75, 124, 159, *np.random.default_rng(seed).choice(160, 20, replace=False).tolist()]))
    index = BatchFlagIndex(frame, pivots, max_horizon=126)
    for t0 in t0s:
        reference = event_flag_observations(frame, pivots, t0, horizons=(20, 126), landmarks=(5, 10))
        ours = index.observations([t0], horizons=(20, 126), landmarks=(5, 10))
        expected = reference.loc[reference.flag_id.isin(APPLICABLE_FLAGS)].reset_index(drop=True)
        actual = ours.loc[ours.flag_id.isin(APPLICABLE_FLAGS), expected.columns].reset_index(drop=True)
        assert_frame_equal(actual, expected, check_exact=True, check_dtype=False)
        assert set(ours.loc[ours.flag_id.isin(["Y1", "Y2"]), "flag_state"]) == {"not_applicable"}
        # Compact production histories must match diagnostic/public histories too.
        for row in expected.itertuples():
            cut = min(row.landmark, int(row.first_hit_offset) - 1) if pd.notna(row.first_hit_offset) else row.landmark
            state, offset = index.histories(row.flag_id, np.array([t0], dtype=np.int64), np.array([cut], dtype=np.int64))
            assert FLAG_STATES[state[0]] == row.flag_state
            assert (None if offset[0] < 0 else int(offset[0])) == (None if pd.isna(row.first_trigger_offset) else int(row.first_trigger_offset))


def test_strict_and_inclusive_edges_and_confirmed_support() -> None:
    frame, pivots = synthetic_frame()
    frame.loc[:, "Close"] = 10.0
    frame.iloc[8, frame.columns.get_loc("Close")] = 9.0
    frame.iloc[9, frame.columns.get_loc("Close")] = 8.5
    frame.loc[:, "SMA20"] = 10.0
    frame.loc[:, "SMA60"] = 10.0
    frame.loc[:, "BBLower"] = 10.0
    index = BatchFlagIndex(frame, pivots)
    assert index.support[6] == 8.0 and index.support[7] == 9.0 and index.support[12] == 9.5
    rows = index.observations([7], horizons=(10,), landmarks=(1, 2))
    l1 = rows.loc[rows.landmark.eq(1)].set_index("flag_id")
    assert l1.loc["Y3", "flag_state"] == "all_false", "close == fixed support is not a strict break"
    assert l1.loc["X6_10", "flag_state"] == "triggered", "close == 90% anchor triggers"
    assert l1.loc["X6_15", "flag_state"] == "all_false"
    assert rows.loc[rows.landmark.eq(2) & rows.flag_id.eq("X6_15"), "flag_state"].item() == "triggered"
    equal = index.observations([30], horizons=(5,), landmarks=(1,))
    assert set(equal.loc[equal.flag_id.isin(["X5_MA20", "X5_MA60", "X7"]), "flag_state"]) == {"all_false"}
    assert assert_observation_parity(frame, pivots, [6, 7, 14, 159]) == 4


def merged_pr(number: int, path: str) -> dict:
    return {
        "number": number,
        "state": "MERGED",
        "mergedAt": "2026-10-24T00:00:00Z",
        "baseRefName": "main",
        "files": [{"path": path}],
        "mergeCommit": {"oid": "a" * 40},
        "url": f"https://github.com/TaiwanCCyoyo/stock-research/pull/{number}",
    }


@pytest.mark.parametrize("invalid", ["open", "wrong_path", "wrong_repo", "wrong_base", "no_commit"])
def test_market_gate_rejects_every_incomplete_or_unrelated_merge(invalid: str) -> None:
    mission = merged_pr(91, "tasks/20261024-strength-weakening-flags/mission.md")
    code = merged_pr(92, "scripts/run_strength_flags.py")
    if invalid == "open":
        code["state"] = "OPEN"
    elif invalid == "wrong_path":
        code["files"] = [{"path": "another.py"}]
    elif invalid == "wrong_repo":
        code["url"] = "https://github.com/other/repo/pull/92"
    elif invalid == "wrong_base":
        code["baseRefName"] = "develop"
    else:
        code["mergeCommit"] = None
    with pytest.raises((RuntimeError, AttributeError)):
        verify_owner_merges(91, 92, lookup=lambda number: mission if number == 91 else code)


def test_alignment_is_exact_and_never_adopts_pr61_tolerance() -> None:
    from research_core.strength_flags_run_v1 import GROUPS, REFERENCE_GROUPS

    actual = pd.DataFrame([
        {"group_id": group, "horizon": horizon, "target_multiple": 2.0, "known_n": 1000, "hit_n": 20, "loss_n": 500}
        for group in GROUPS
        for horizon in (126, 252)
    ])
    reference = actual.copy()
    reference["group_id"] = reference.group_id.map(REFERENCE_GROUPS)
    require_exact_alignment(compare_reference(actual, reference))
    actual.loc[0, "loss_n"] += 1
    comparison = compare_reference(actual, reference)
    assert comparison.delta_loss_n.sum() == 1
    with pytest.raises(AlignmentError, match="stop for owner"):
        require_exact_alignment(comparison)


def test_fast_index_refuses_unindexed_horizons_and_cutoffs() -> None:
    frame, pivots = synthetic_frame()
    index = BatchFlagIndex(frame, pivots, max_horizon=20)
    with pytest.raises(ValueError, match="indexed maximum"):
        index.observations([0], horizons=(21,))
    with pytest.raises(ValueError, match="indexed calendar/horizon"):
        index.histories("Y3", np.array([0], dtype=np.int64), np.array([21], dtype=np.int64))


def test_shared_source_selection_is_used_and_future_asof_is_never_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import strength_flags_run_v1 as run
    from scripts.tests.test_strength_flag_counts_v1 import example_stock

    stock, index, _ = example_stock()
    monkeypatch.setattr(run, "current_generation", lambda **kwargs: {"asof": "2026-10-23"})
    monkeypatch.setattr(run, "read_technical", lambda *args, **kwargs: pytest.fail("future-asof technical table must not be read"))
    result = run.indicator_probe(["2330"], "fictional-generation")
    assert result["selected"] == [] and "another asof" in result["reason"]
    values = np.arange(index.n, dtype=float) + 123
    shared = pd.DataFrame({"Code": "2330", "Date": index.frame.index, "SMA20": values, "raw_return1": np.full(index.n, 0.095)})
    shared.loc[0, "raw_return1"] = np.nan
    monkeypatch.setattr(run, "read_technical", lambda *args, **kwargs: (shared, {}))
    monkeypatch.setattr(run.momentum, "stock_daily", lambda code, prepared: stock)
    monkeypatch.setattr(run, "prepare_detector_frame", lambda prepared: (index.frame.copy(), index.pivots))
    actual, frame, _ = run._study_stock("2330", pd.DataFrame(), "fictional-generation", ("daily:SMA20:SMA20", "conditions:G2_limit:raw_return1"))
    assert np.array_equal(frame.SMA20, values)
    assert actual.atoms["A3"][0] == -1 and np.all(actual.atoms["A3"][1:] == 1)


def test_final_json_lf_and_same_run_finalize_recovery_preserve_bytes(tmp_path: Path) -> None:
    from research_core import strength_flags_run_v1 as run
    from research_core.artifact_store import write_json

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    timings = scratch / "timings.json"
    initial = {"phases": [{"wall_seconds": 12}], "cost": {"workers": 1}}
    run.save_timings(timings, initial, resume=False)
    source = timings.read_bytes()
    assert not source.endswith(b"\n")
    destination = tmp_path / "results"
    run.publish_final_outputs(scratch, [timings], destination, run_id="fictional", code_commit="a" * 40, resume=False)
    published = destination / "timings.json"
    assert published.read_bytes() == source + b"\n" and timings.read_bytes() == source
    run.save_timings(timings, {"phases": [{"wall_seconds": 999}], "cost": {}}, resume=True)
    assert timings.read_bytes() == source
    run.publish_final_outputs(scratch, [timings], destination, run_id="fictional", code_commit="a" * 40, resume=True)
    assert published.read_bytes() == source + b"\n"
    receipt = destination / "run-receipt.json"
    write_json(
        receipt,
        {
            "schema": "run-receipt.v1",
            "run_id": "fictional",
            "code": {"commit": "a" * 40},
            "results": {
                "timings": {"path": "results/timings.json", "bytes": published.stat().st_size, "sha256": hashlib.sha256(published.read_bytes()).hexdigest()}
            },
        },
    )
    receipt_bytes = receipt.read_bytes()
    assert run.reusable_receipt(receipt, run_id="fictional", code_commit="a" * 40, resume=True, expected_results=["timings"], repo_root=tmp_path)
    assert receipt.read_bytes() == receipt_bytes
    with pytest.raises(RuntimeError, match="different run"):
        run.publish_final_outputs(scratch, [timings], destination, run_id="another", code_commit="a" * 40, resume=True)
    published.write_bytes(b"changed\n")
    with pytest.raises(RuntimeError, match="differ"):
        run.reusable_receipt(receipt, run_id="fictional", code_commit="a" * 40, resume=True, expected_results=["timings"], repo_root=tmp_path)


def test_probe_releases_only_its_matching_hold_and_does_not_claim_study_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import strength_flags_run_v1 as run
    from research_core.scratch_runs import ScratchRun

    released = []
    own = {"holder": run.HOLDER, "generation": "fictional-generation", "reason": "this-probe"}
    foreign = {"holder": "pr17-pattern-scan", "generation": "protected", "reason": "other-reader"}
    monkeypatch.setattr(run, "held_generations", lambda: {"fictional-generation": [own], "protected": [foreign]})
    monkeypatch.setattr(run, "release_generation", lambda holder: released.append(holder))
    record = {"state": "running"}
    fake = cast(ScratchRun, SimpleNamespace(path=tmp_path, record=record, mark=lambda state: record.update(state=state)))
    run.finish_resource_probe(fake, generation="fictional-generation", reason="this-probe")
    assert released == [run.HOLDER] and record["state"] == "complete"
    assert json.loads((tmp_path / "probe-only.json").read_text(encoding="utf-8"))["research_complete"] is False
    own["reason"] = "another-run"
    released.clear()
    with pytest.raises(RuntimeError, match="another reader"):
        run.finish_resource_probe(fake, generation="fictional-generation", reason="this-probe")
    assert released == []


def test_one_pool_serves_every_batch_with_bounded_in_flight_and_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import strength_flags_run_v1 as run

    jobs = [(f"{number:04}", "fictional-generation", "fictional-directory", ()) for number in range(20)]
    pool = MagicMock()
    batches = []

    def mapped(
        function: Callable[[tuple[str, str, str, tuple[str, ...]]], dict[str, str]], batch: Sequence[tuple[str, str, str, tuple[str, ...]]]
    ) -> list[dict[str, str]]:
        batches.append(list(batch))
        return [function(job) for job in batch]

    pool.map.side_effect = mapped
    factory = MagicMock()
    factory.return_value.__enter__.return_value = pool
    monkeypatch.setattr(run, "ProcessPoolExecutor", factory)
    monkeypatch.setattr(run, "_count_job", lambda job: {"code": job[0]})
    progress = []
    result = run._bounded_jobs(jobs, 4, progress=lambda done, total: progress.append((done, total)))
    factory.assert_called_once_with(max_workers=4)
    assert all(len(batch) <= 4 for batch in batches)
    assert [row["code"] for row in result] == [job[0] for job in jobs]
    assert progress == [(4, 20), (8, 20), (12, 20), (16, 20), (20, 20)]
    factory.reset_mock()
    progress.clear()
    assert run._bounded_jobs(jobs[:3], 1, progress=lambda done, total: progress.append((done, total))) == result[:3]
    factory.assert_not_called()
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_resume_keeps_original_clean_checkout_after_main_advances(monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import strength_flags_run_v1 as run

    calls = []

    def git_command(args: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(args)
        if args[:4] == ["git", "merge-base", "--is-ancestor", "origin/main"]:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(returncode=0)

    original_code = {"commit": "a" * 40, "dirty": False}
    merges = [{"mergeCommit": {"oid": "b" * 40}}, {"mergeCommit": {"oid": "c" * 40}}]
    monkeypatch.setattr(run.subprocess, "run", git_command)
    monkeypatch.setattr(run, "code_identity", lambda root: original_code)
    with pytest.raises(subprocess.CalledProcessError):
        run.verify_execution_checkout(merges)
    calls.clear()
    assert run.verify_execution_checkout(merges, resume=True) == original_code
    assert ["git", "fetch", "origin"] in calls
    assert ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"] not in calls
    assert all(["git", "merge-base", "--is-ancestor", record["mergeCommit"]["oid"], "HEAD"] in calls for record in merges)
    original_code["dirty"] = True
    with pytest.raises(RuntimeError, match="clean committed code"):
        run.verify_execution_checkout(merges, resume=True)


def test_resume_rejects_changed_commit_before_touching_holds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from research_core import strength_flags_run_v1 as run

    (tmp_path / "execution.json").write_text(json.dumps({"code": {"commit": "a" * 40}, "probe": False, "generation": "held"}), encoding="utf-8")
    context = MagicMock()
    context.__enter__.return_value = SimpleNamespace(path=tmp_path)
    monkeypatch.setattr(run, "verify_owner_merges", lambda *args: [])
    monkeypatch.setattr(run, "verify_execution_checkout", lambda merges, **kwargs: {"commit": "b" * 40, "dirty": False})
    monkeypatch.setattr(run, "assert_producer_idle", lambda: None)
    monkeypatch.setattr(run.momentum, "pr17_calendar", lambda: pd.bdate_range("2010-01-04", periods=10))
    monkeypatch.setattr(run.momentum, "pr17_codes", lambda: ["2330"])
    monkeypatch.setattr(run, "current_generation", lambda: {"generation": "current"})
    monkeypatch.setattr(run, "open_run", lambda *args, **kwargs: context)
    monkeypatch.setattr(run, "held_generations", lambda: pytest.fail("changed code must fail before any hold operation"))
    with pytest.raises(RuntimeError, match="same committed code"):
        run.run_study(mission_pr=91, code_pr=93, run_id="fictional", owner="test", resume=True)

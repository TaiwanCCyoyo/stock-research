"""Synthetic parity for the bounded, results-only Q5--Q6 local phase."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import artifact_store
from research_core import pattern_scan_local_followup_v5 as local
from research_core.hhhl_variants_observations import classify_window
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_failure_summary_v1 import FailureAccumulator
from research_core.pattern_scan_followup_summary_v1 import FollowupAccumulator
from research_core.pattern_scan_followup_v1 import FollowupTables, followup_values
from research_core.pattern_scan_holding_v1 import holding_values
from research_core.pattern_scan_reporting_v1 import candidate_membership


class SyntheticInputs:
    codes: tuple[str, ...] = ("0001", "0002", "0003")

    def __init__(self) -> None:
        self.calendar = pd.bdate_range("2011-01-03", periods=300)
        self.closes = pd.DataFrame(
            {
                "TW:0001": np.linspace(100.0, 60.0, len(self.calendar)),
                "TW:0002": 100.0 + np.arange(len(self.calendar)) * 0.5,
                "TW:0003": np.linspace(100.0, 130.0, len(self.calendar)),
            },
            index=self.calendar,
        )
        self.jumps = pd.DataFrame(False, index=self.calendar, columns=self.closes.columns)
        self.industries = dict.fromkeys(self.closes.columns, "synthetic-industry")
        self.benchmark = pd.Series(100.0 + np.arange(len(self.calendar)) * 0.1, index=self.calendar)
        self.states = pd.Series("up", index=self.calendar)
        self.holding_calls: list[tuple[str, list[int]]] = []
        self.bound_calls: list[str] = []

    def stock(self, code: str) -> dict[str, pd.DataFrame]:
        close = self.closes[f"TW:{code}"]
        indicator = pd.DataFrame({"Close": close, "SMA20": close + 1.0, "SMA60": close + 2.0, "BBLower": close - 5.0})
        pivots = pd.DataFrame(columns=pd.Index(["k", "kind", "extreme_index", "confirmation_index", "extreme_date", "confirmed_at", "price"]))
        return {"indicators": indicator, "pivots": pivots}

    def bound(self, target: str, code: str) -> pd.DataFrame:
        assert target == "R1"
        self.bound_calls.append(code)
        rows = []
        closes = self.closes[f"TW:{code}"].tolist()
        for horizon in local.HORIZONS:
            for anchor in () if code == "0003" else (0, 20, 280):
                clock = classify_window(closes[anchor:], horizon)
                rows.append({
                    "security_id": f"TW:{code}",
                    "event_id": f"{code}:{anchor}",
                    "t0": self.calendar.strftime("%Y-%m-%d")[anchor],
                    "calendar_index": anchor,
                    "horizon": horizon,
                    "pattern_id": target,
                    "subtype_id": "R1a",
                    "cohort_id": "union",
                    "base_label": clock.outcome,
                    "effective_label": clock.outcome,
                    "calendar_full": clock.calendar_full,
                    "base_main_eligible": clock.main_eligible,
                    "event_main_eligible": clock.main_eligible,
                    "event_eligibility_excluded": False,
                    "base_first_hit_offset": clock.first_hit_offset,
                    "support": closes[anchor] * 0.9,
                    "lower": closes[anchor] * 0.8,
                    "confirmed_support": closes[anchor] * 0.95,
                    "base_label_version_id": "synthetic-labels",
                    "base_label_manifest_sha256": "existing-historical-pin",
                    "detection_quality_reasons_json": "[]",
                    "result_quality_reasons_json": "[]",
                    "event_eligibility_reasons_json": "[]",
                    "effective_unknown_reasons_json": "[]",
                    "F_status": "feature_unknown" if anchor == 280 else "known",
                    "F_bin": "selected" if anchor == 0 else "other",
                    "mkt": "unknown" if anchor == 280 else "up",
                })
        if rows:
            result = pd.DataFrame(rows)
            result["base_first_hit_offset"] = pd.array([row["base_first_hit_offset"] for row in rows], dtype="Int64")
            return result
        return self.bound("R1", "0001").iloc[:0].copy()

    @staticmethod
    def group_frame(bound: pd.DataFrame, group: str, horizon: int) -> pd.DataFrame:
        assert group == "pattern:union"
        return bound.loc[bound.horizon.eq(horizon)].copy()

    def holding(self, code: str, anchors: list[int]) -> pd.DataFrame:
        self.holding_calls.append((code, anchors))
        return holding_values(
            self.closes,
            self.industries,
            self.benchmark,
            self.states,
            jump_matrix=self.jumps,
            benchmark_jump=pd.Series(False, index=self.calendar),
            anchors={f"TW:{code}": anchors},
        )


def _oracle(inputs: SyntheticInputs, candidates: dict[str, tuple[Atom, ...]]) -> dict[str, pd.DataFrame]:
    groups = {"R1": "R1", **dict.fromkeys(candidates, "R1")}
    followup, failure = FollowupAccumulator(groups), FailureAccumulator(groups)
    for code in inputs.codes[:2]:
        original = inputs.bound("R1", code)
        stock = inputs.stock(code)
        base = followup_values(original, stock["indicators"], stock["pivots"])
        first = original.loc[original.horizon.eq(126)]
        ids = {"R1": set(original.event_id)}
        ids.update({identifier: set(first.loc[candidate_membership(first, atoms) == 1, "event_id"]) for identifier, atoms in candidates.items()})
        chunks: dict[str, list[pd.DataFrame]] = {field.name: [] for field in fields(base)}
        markets = original.drop_duplicates("event_id").set_index("event_id")["mkt"]
        for group, selected in ids.items():
            if not selected:
                continue
            for field in fields(base):
                frame = getattr(base, field.name)
                frame = frame.loc[frame.event_id.isin(selected)].copy()
                frame["group_id"], frame["target_pattern_id"] = group, "R1"
                frame["mkt"] = frame.event_id.map(markets)
                chunks[field.name].append(frame)
        tables = FollowupTables(*(pd.concat(chunks[field.name], ignore_index=True) for field in fields(base)))
        followup.add_stock(tables)
        failure.add_stock(tables, inputs.holding(code, [0, 20, 280]))
    return {field.name: getattr(result, field.name) for result in (followup.finalize(), failure.finalize()) for field in fields(result)}


def test_exact_oracle_parity_nonhit_holding_empty_candidate_and_no_temp_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates: dict[str, tuple[Atom, ...]] = {
        "candidate-selected": (Atom("synthetic", "F", "selected"),),
        "candidate-empty": (Atom("synthetic", "F", "never-observed"),),
    }
    expected = _oracle(SyntheticInputs(), candidates)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Q5--Q6 must not hash inputs or intermediate projections")

    for name in ("file_digest", "object_digest", "describe_file", "verify_files"):
        monkeypatch.setattr(artifact_store, name, forbidden)
    calls = []
    numerical_followup = local.followup_values

    def observed_followup(*args: Any, **kwargs: Any) -> FollowupTables:
        calls.append(args[0].security_id.iloc[0])
        return numerical_followup(*args, **kwargs)

    monkeypatch.setattr(local, "followup_values", observed_followup)
    inputs = SyntheticInputs()
    result_paths = local.run_followup(cast(Any, inputs), "R1", candidates, tmp_path / "results")
    assert len(result_paths) == 9
    assert calls == ["TW:0001", "TW:0002"]  # Once per target/stock, not group/H.
    assert inputs.holding_calls == [("0001", [0, 20, 280]), ("0002", [0, 20, 280])] * 4
    for path in result_paths:
        actual = pd.read_parquet(path)
        pd.testing.assert_frame_equal(actual, expected[path.stem], check_exact=True)
    nonhit = pd.read_parquet(tmp_path / "results" / "holding_by_outcome.parquet")
    nonhit = nonhit.loc[nonhit.group_id.eq("R1") & nonhit.population.eq("nonhit") & nonhit.sample_n.gt(0)]
    assert not nonhit.empty and nonhit.peer_return_known_n.gt(0).any()
    # The peer with no events remains in the full-universe holding calculation.
    holding = inputs.holding("0001", [0, 20, 280])
    assert holding.potential_peer_n.eq(2).all()
    empty = pd.read_parquet(tmp_path / "results" / "path_summary.parquet")
    assert empty.loc[empty.group_id.eq("candidate-empty"), "event_n"].eq(0).all()
    temporary = tmp_path / "results" / "_temporary"
    assert list(temporary.rglob("*.json")) == [temporary / "progress.json"]
    progress = artifact_store.read_json(temporary / "progress.json")
    assert progress["completed"] == ["0001", "0002", "0003"] and progress["empty"] == ["0003"]
    assert "artifacts" not in progress and "sha256" not in progress
    assert not list(temporary.rglob("holding.parquet"))
    for path in (tmp_path / "results").rglob("*.parquet"):
        metadata = pq.read_metadata(path)
        codecs = {metadata.row_group(row).column(column).compression for row in range(metadata.num_row_groups) for column in range(metadata.num_columns)}
        assert codecs <= {"ZSTD"}


def test_empty_candidates_keep_original_pattern_and_reuse_complete_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = SyntheticInputs()
    inputs.codes = ()
    paths = local.run_followup(cast(Any, inputs), "R1", {"R1": ()}, tmp_path / "empty")
    assert len(paths) == 9
    frame = pd.read_parquet(tmp_path / "empty" / "path_summary.parquet")
    assert set(frame.group_id) == {"R1"} and frame.event_n.eq(0).all()
    retained = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    assert local.completed_results(tmp_path / "empty") == paths
    assert local.run_followup(cast(Any, inputs), "R1", {}, tmp_path / "empty") == paths
    assert retained == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}


def test_interrupted_phase_reuses_completed_stock_without_hashes_or_recalculation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = SyntheticInputs()
    numerical_followup = local.followup_values
    calls = []

    def interrupted(events: pd.DataFrame, *args: Any, **kwargs: Any) -> FollowupTables:
        code = events.security_id.iloc[0]
        calls.append(code)
        if code == "TW:0002":
            raise RuntimeError("synthetic interruption before second stock")
        return numerical_followup(events, *args, **kwargs)

    output = tmp_path / "resume"
    monkeypatch.setattr(local, "followup_values", interrupted)
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        local.run_followup(cast(Any, inputs), "R1", {}, output)
    original = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (output / "_temporary" / "0001").glob("*.parquet")}
    assert len(original) == 4
    assert artifact_store.read_json(output / "_temporary" / "progress.json")["completed"] == ["0001"]

    def resumed(events: pd.DataFrame, *args: Any, **kwargs: Any) -> FollowupTables:
        calls.append(events.security_id.iloc[0])
        assert events.security_id.iloc[0] == "TW:0002"
        return numerical_followup(events, *args, **kwargs)

    monkeypatch.setattr(local, "followup_values", resumed)
    paths = local.run_followup(cast(Any, inputs), "R1", {}, output)
    assert len(paths) == 9
    assert calls == ["TW:0001", "TW:0002", "TW:0002"]
    assert original == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in original}


def test_partial_final_write_resumes_only_failure_family_and_complete_retry_reads_no_stocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = _oracle(SyntheticInputs(), {})
    inputs = SyntheticInputs()
    numerical_followup, parquet_write = local.followup_values, local._write
    kernels: list[str] = []

    def observed_followup(events: pd.DataFrame, *args: Any, **kwargs: Any) -> FollowupTables:
        kernels.append(events.security_id.iloc[0])
        return numerical_followup(events, *args, **kwargs)

    def interrupted_write(path: Path, table: pd.DataFrame, *, incomplete: bool = False) -> None:
        if not incomplete and path.stem == "first_flag_by_outcome":
            path.write_bytes(b"PAR1interrupted before the footer")
            raise RuntimeError("synthetic partial final table")
        parquet_write(path, table, incomplete=incomplete)

    monkeypatch.setattr(local, "followup_values", observed_followup)
    monkeypatch.setattr(local, "_write", interrupted_write)
    output = tmp_path / "partial-finals"
    with pytest.raises(RuntimeError, match="partial final table"):
        local.run_followup(cast(Any, inputs), "R1", {}, output)
    assert kernels == ["TW:0001", "TW:0002"]
    assert local.completed_results(output) is None
    retained = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in output.glob("*.parquet") if path.stem != "first_flag_by_outcome"}
    retained.update({path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (output / "_temporary").rglob("*.parquet")})
    assert len(retained) == 15  # Seven complete final tables and eight projections.

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("retry must reuse stock projections and the complete other summary family")

    reductions: list[int] = []

    class ObservedFailure(FailureAccumulator):
        def __init__(self, groups: Any, *, horizons: Any) -> None:
            reductions.extend(horizons)
            super().__init__(groups, horizons=horizons)

    monkeypatch.setattr(local, "_write", parquet_write)
    monkeypatch.setattr(local, "followup_values", forbidden)
    monkeypatch.setattr(inputs, "stock", forbidden)
    monkeypatch.setattr(local.followup_summary, "FollowupAccumulator", forbidden)
    monkeypatch.setattr(local.failure_summary, "FailureAccumulator", ObservedFailure)
    for name in ("file_digest", "object_digest", "describe_file", "verify_files"):
        monkeypatch.setattr(artifact_store, name, forbidden)
    paths = local.run_followup(cast(Any, inputs), "R1", {}, output)
    assert reductions == [126, 252]
    assert kernels == ["TW:0001", "TW:0002"]
    assert retained == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in retained}
    for path in paths:
        pd.testing.assert_frame_equal(pd.read_parquet(path), expected[path.stem], check_exact=True)

    all_retained = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    monkeypatch.setattr(inputs, "bound", forbidden)
    monkeypatch.setattr(inputs, "holding", forbidden)
    monkeypatch.setattr(local, "_summaries", forbidden)
    assert local.completed_results(output) == paths
    assert local.run_followup(cast(Any, inputs), "R1", {}, output) == paths
    assert all_retained == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}


def test_missing_followup_table_skips_failure_family_and_holding(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inputs = SyntheticInputs()
    inputs.codes = ()
    output = tmp_path / "followup-family"
    paths = local.run_followup(cast(Any, inputs), "R1", {}, output)
    damaged = output / "flag_summary.parquet"
    expected = pd.read_parquet(damaged)
    retained = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths if path != damaged}
    damaged.write_bytes(b"PAR1unfinished")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("missing followup member must not calculate the complete failure family or holding")

    reductions: list[int] = []

    class ObservedFollowup(FollowupAccumulator):
        def __init__(self, groups: Any, *, horizons: Any) -> None:
            reductions.extend(horizons)
            super().__init__(groups, horizons=horizons)

    monkeypatch.setattr(local.followup_summary, "FollowupAccumulator", ObservedFollowup)
    monkeypatch.setattr(local.failure_summary, "FailureAccumulator", forbidden)
    monkeypatch.setattr(inputs, "holding", forbidden)
    assert local.run_followup(cast(Any, inputs), "R1", {}, output) == paths
    assert reductions == [126, 252]
    pd.testing.assert_frame_equal(pd.read_parquet(damaged), expected, check_exact=True)
    assert retained == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in retained}


def test_completed_results_rejects_readable_wrong_schema(tmp_path: Path) -> None:
    inputs = SyntheticInputs()
    inputs.codes = ()
    output = tmp_path / "wrong-schema"
    local.run_followup(cast(Any, inputs), "R1", {}, output)
    assert local.completed_results(output) is not None
    pd.DataFrame({"wrong_column": [1]}).to_parquet(output / "path_summary.parquet", compression="zstd")
    assert local.completed_results(output) is None


@pytest.mark.parametrize("candidates", [{"bad": ()}, {f"candidate-{n}": (Atom("synthetic", "F", "selected"),) for n in range(11)}])
def test_invalid_candidate_registry_fails_before_input_reads(tmp_path: Path, candidates: dict[str, tuple[Atom, ...]]) -> None:
    with pytest.raises(ValueError, match="candidates"):
        local.run_followup(cast(Any, None), "R1", candidates, tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()

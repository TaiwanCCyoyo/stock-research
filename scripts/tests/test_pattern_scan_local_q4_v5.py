"""Q4 final-only adapter equivalence over synthetic original-study inputs."""

from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_local_q4_v5 as module
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_candidate_daily_v1 import daily_candidate_states
from research_core.pattern_scan_episode_coverage_v1 import CONTROL_COLUMNS, random_matched_control
from research_core.pattern_scan_episode_tables_v1 import daily_base_coverage, grouped_coverage, observe_group, per_stock_episodes, random_control_coverage
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_event_tables_v1 import EventTables
from research_core.pattern_scan_reporting_v1 import candidate_membership
from research_core.pattern_scan_retained_v3 import select_q4_examples


class Inputs:
    codes = ("0050", "2330")
    calendar = pd.bdate_range("2010-01-04", periods=220)
    source_id = "synthetic-source"
    input_id = "synthetic-input"

    def __init__(self) -> None:
        self.bound_calls: list[tuple[str, str]] = []

    def stock(self, code: str) -> dict[str, pd.DataFrame]:
        prices = pd.DataFrame({"Close": 100.0, "Low": 80.0, "quality_reason": None}, index=self.calendar)
        prices.iloc[80, prices.columns.get_loc("Close")] = 200.0
        if code == "2330":
            prices.iloc[75, prices.columns.get_loc("Close")] = np.nan
            prices.iloc[75, prices.columns.get_loc("quality_reason")] = "missing_price"
        common = pd.DataFrame({"G": 1.2, "MA_b": True}, index=self.calendar)
        common.iloc[100, common.columns.get_loc("MA_b")] = False
        states = np.zeros(len(self.calendar), dtype=np.int8)
        states[[60, 100]] = 1
        states[31] = -1
        rows: list[dict[str, Any]] = []
        for t in (60, 100):
            identity = EventIdentity(f"TW:{code}", str(self.calendar[t].strftime("%Y-%m-%d")), "B1", "first", self.source_id, self.input_id)
            rows.append({
                "event_id": identity.event_id,
                "security_id": f"TW:{code}",
                "t0": identity.t0,
                "calendar_index": t,
                "pattern_id": "B1",
                "subtype_id": "first",
                "definition_id": self.source_id,
                "input_id": self.input_id,
                "support": 99.0,
                "pivot": 95.0,
                "details_json": "{}",
            })
        labels = pd.DataFrame({
            "calendar_index": [50, 51, 200],
            "horizon": [126] * 3,
            "label": ["hit", "unknown", "hit"],
            "calendar_full": [True, True, False],
        })
        return {
            "prices": prices,
            "indicators": prices,
            "common_values": common,
            "raw_events": pd.DataFrame(rows),
            "pattern_states": pd.DataFrame({"B1": states}, index=self.calendar),
            "base_labels": labels,
        }

    def global_values(self, code: str) -> pd.DataFrame:
        return pd.DataFrame({"MKT": "up" if code == "0050" else "unknown"}, index=self.calendar)

    def bound(self, target: str, code: str) -> EventTables:
        assert target == "B1"
        self.bound_calls.append((target, code))
        raw = self.stock(code)["pattern_states"].B1
        c52 = pd.Series(np.zeros(len(self.calendar), dtype=np.int8), index=self.calendar)
        c52.iloc[60] = 1
        return EventTables(
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
            {"pattern:union": raw, "C-52w": c52, "C-base-daily": pd.Series(np.ones(len(self.calendar), dtype=np.int8), index=self.calendar)},
            {},
        )

    def group_frame(self, bound: EventTables, group: str, horizon: int) -> pd.DataFrame:
        assert horizon == 126
        # The stock id normally comes from the existing EventTables. Attach it
        # here through the just-requested bound call, keeping the fixture small.
        code = self.bound_calls[-1][1]
        indices = (60, 100) if group == "pattern:union" else (60,) if group == "C-52w" else (60,)
        return pd.DataFrame({
            "security_id": [f"TW:{code}"] * len(indices),
            "calendar_index": indices,
            "t0": [self.calendar[t].strftime("%Y-%m-%d") for t in indices],
            "base_eligible": True,
            "MA_b_status": "known",
            "MA_b_bin": ["false" if t == 100 else "true" for t in indices],
        })


def _atom() -> Atom:
    return next(atom for atom in atoms_for_pattern("B1") if atom.feature_id == "MA_b" and atom.bin_id == "true")


def _legacy_rows(inputs: Inputs, candidates: dict[str, tuple[Atom, ...]]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    observations, draws, quotas = [], [], []
    dates = tuple(inputs.calendar.strftime("%Y-%m-%d"))
    for code in inputs.codes:
        tables = inputs.stock(code)
        prices = tables["prices"]
        closes = [None if pd.isna(value) else float(value) for value in prices.Close]
        reasons = [None if pd.isna(value) else str(value) for value in prices.quality_reason]
        episodes, _ = per_stock_episodes(closes, tables["base_labels"], reasons, f"TW:{code}", dates=dates)
        market = inputs.global_values(code).MKT.tolist()
        bound = inputs.bound("B1", code)
        retained = inputs.group_frame(bound, "pattern:union", 126)
        pool = inputs.group_frame(bound, "C-base-all", 126)
        c52 = inputs.group_frame(bound, "C-52w", 126)
        daily = pd.DataFrame(bound.daily_groups)
        observations.append(daily_base_coverage(episodes, closes, dates, daily["C-base-daily"].tolist(), market, f"TW:{code}", group_id="C-base-daily"))
        common = tables["common_values"].assign(MKT=market)
        states = (
            daily_candidate_states(
                "B1",
                tables["raw_events"],
                tables["indicators"],
                common,
                tables["pattern_states"].B1.to_numpy(dtype=np.int8),
                security_id=f"TW:{code}",
                definition_id=inputs.source_id,
                input_id=inputs.input_id,
                candidates=candidates,
            )
            if candidates
            else {}
        )
        for candidate in (None, *candidates):
            identifier = "B1:original" if candidate is None else f"B1:candidate:{candidate}"
            targets = retained if candidate is None else retained.loc[candidate_membership(retained, candidates[candidate]) == 1]
            daily_states = daily["pattern:union"].tolist() if candidate is None else states[candidate].tolist()
            observations.append(observe_group(episodes, closes, dates, targets.calendar_index.tolist(), daily_states, market, f"TW:{code}", identifier))
            observations.append(
                observe_group(episodes, closes, dates, c52.calendar_index.tolist(), daily["C-52w"].tolist(), market, f"TW:{code}", identifier + ":C-52w")
            )
            observed, drawn, quota = random_control_coverage(
                pool,
                targets,
                group_id=identifier + ":C-base-random",
                episodes=episodes,
                closes=closes,
                dates=dates,
                anchor_regime=market,
                security_id=f"TW:{code}",
                pool_pin="fixture-only",
            )
            observations.append(observed)
            drawn["group_id"], quota["group_id"] = identifier + ":C-base-random", identifier + ":C-base-random"
            draws.append(drawn)
            quotas.append(quota.drop(columns=["pool_pin", "pool_digest"]))
    return pd.concat(observations, ignore_index=True), pd.concat(draws, ignore_index=True), pd.concat(quotas, ignore_index=True)


@pytest.mark.parametrize("candidate", (False, True))
def test_final_q4_equals_legacy_pure_kernels_without_payload_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, candidate: bool) -> None:
    candidates: dict[str, tuple[Atom, ...]] = {"ma": (_atom(),)} if candidate else {}
    expected_rows, expected_draws, expected_quotas = _legacy_rows(Inputs(), candidates)
    expected_coverage = pd.DataFrame([row for row in grouped_coverage(expected_rows) if row["split"] != "all"])

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Q4 must not hash inputs/intermediate files or describe intermediate artifacts")

    monkeypatch.setattr("research_core.artifact_store.file_digest", forbidden)
    monkeypatch.setattr("research_core.artifact_store.describe_file", forbidden)
    monkeypatch.setattr("research_core.artifact_store.verify_files", forbidden)
    original_digest = module.object_digest

    def seed_only(value: Any) -> str:
        assert set(value) == {"seed", "group_id", "security_id", "year"}
        assert value["seed"] == 20261013
        return original_digest(value)

    monkeypatch.setattr(module, "object_digest", seed_only)
    inputs = Inputs()
    output = tmp_path / "q4"
    paths = module.run_q4(cast(Any, inputs), "B1", candidates, output)
    assert inputs.bound_calls == [("B1", "0050"), ("B1", "2330")]
    assert {path.name for path in paths} == {
        "coverage.parquet",
        "timing.parquet",
        "examples.parquet",
        "admission-counts.parquet",
        "draws.parquet",
        "quotas.parquet",
    }
    assert {path for path in output.iterdir() if path.is_file()} == set(paths)
    assert (output / "_temporary/progress.json").is_file()
    actual = pd.read_parquet(output / "coverage.parquet")
    pd.testing.assert_frame_equal(actual.loc[:, expected_coverage.columns], expected_coverage, check_dtype=False)
    pd.testing.assert_frame_equal(pd.read_parquet(output / "draws.parquet"), expected_draws, check_dtype=False)
    pd.testing.assert_frame_equal(pd.read_parquet(output / "quotas.parquet"), expected_quotas, check_dtype=False)
    pd.testing.assert_frame_equal(pd.read_parquet(output / "examples.parquet"), select_q4_examples(expected_rows), check_dtype=False)
    counts = pd.read_parquet(output / "admission-counts.parquet")
    assert counts.loc[counts.measure.eq("start_n"), "count"].sum() == 6
    assert counts.loc[counts.measure.eq("excluded_n"), "count"].sum() == 4
    assert counts.loc[counts.measure.eq("excluded:base_unknown"), "count"].sum() == 2
    assert "pool_digest" not in expected_quotas and "pool_pin" not in expected_quotas
    assert actual.unknown_n.sum() > 0
    for path in paths:
        metadata = pq.read_metadata(path)
        assert {metadata.row_group(r).column(c).compression for r in range(metadata.num_row_groups) for c in range(metadata.num_columns)} <= {"ZSTD"}


def test_random_draw_order_and_year_shortfalls_match_legacy() -> None:
    rows = [("TW:0050", index, f"{year}-01-{day:02}") for year, index, day in ((2010, 0, 1), (2010, 22, 2), (2011, 300, 1), (2011, 322, 2))]
    pool = pd.DataFrame(rows[::-1], columns=pd.Index(CONTROL_COLUMNS))
    targets = pool.iloc[[0, 1, 2]].copy()
    extra = pd.DataFrame([("TW:2330", 0, "2010-01-01")], columns=pd.Index(CONTROL_COLUMNS))
    targets = pd.concat([targets, extra], ignore_index=True)
    expected_draws, expected_quotas = random_matched_control(pool, targets, "B1:original:C-base-random")
    draws, quotas = module.random_matched_control(pool, targets, "B1:original:C-base-random")
    pd.testing.assert_frame_equal(draws, expected_draws)
    pd.testing.assert_frame_equal(quotas, expected_quotas.drop(columns="pool_digest"))
    assert quotas.shortfall.sum() == 1


def test_zero_episodes_keep_all_final_coverage_cells(tmp_path: Path) -> None:
    class EmptyInputs(Inputs):
        def stock(self, code: str) -> dict[str, pd.DataFrame]:
            tables = super().stock(code)
            tables["base_labels"].loc[:, "label"] = "unknown"
            return tables

    output = tmp_path / "empty"
    module.run_q4(cast(Any, EmptyInputs()), "B1", {}, output)
    coverage = pd.read_parquet(output / "coverage.parquet")
    assert len(coverage) == 4 * 48
    assert coverage.episode_n.eq(0).all()
    assert pd.read_parquet(output / "examples.parquet").empty


def test_invalid_scope_is_rejected_without_reads(tmp_path: Path) -> None:
    inputs = Inputs()
    cases: tuple[tuple[str, dict[str, tuple[Atom, ...]]], ...] = (("unknown", {}), ("B1", {str(index): (_atom(),) for index in range(11)}))
    for target, candidates in cases:
        with pytest.raises(ValueError, match="at most ten"):
            module.run_q4(cast(Any, inputs), target, candidates, tmp_path / "unused")
    assert inputs.bound_calls == []


def test_partial_final_retry_preserves_valid_bytes_and_reuses_stock_projections(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates: dict[str, tuple[Atom, ...]] = {"ma": (_atom(),)}
    expected_rows, expected_draws, expected_quotas = _legacy_rows(Inputs(), candidates)
    oracle_paths = module.run_q4(cast(Any, Inputs()), "B1", candidates, tmp_path / "oracle")
    oracle = {path.name: pd.read_parquet(path) for path in oracle_paths}
    output = tmp_path / "q4"
    write = module._write
    episode_builder = module.per_stock_episodes
    built: list[str] = []

    def counted_episodes(*args: Any, **kwargs: Any) -> Any:
        built.append(str(args[3]))
        return episode_builder(*args, **kwargs)

    def interrupted_write(directory: Path, name: str, frame: pd.DataFrame) -> Path:
        if name == "examples.parquet":
            # Model interruption during a non-atomic old final write as well
            # as the missing files that have not been reached yet.
            (directory / name).write_bytes(b"partial parquet")
            raise OSError("synthetic interruption after two final tables")
        return write(directory, name, frame)

    monkeypatch.setattr(module, "per_stock_episodes", counted_episodes)
    monkeypatch.setattr(module, "_write", interrupted_write)
    with pytest.raises(OSError, match="synthetic interruption"):
        module.run_q4(cast(Any, Inputs()), "B1", candidates, output)
    assert built == ["TW:0050", "TW:2330"]
    assert module.completed_results(output) is None
    preserved = {name: ((output / name).read_bytes(), (output / name).stat().st_mtime_ns) for name in ("coverage.parquet", "timing.parquet")}

    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("partial final recovery must reuse completed stock projections")

    retry = Inputs()
    monkeypatch.setattr(retry, "stock", forbidden)
    monkeypatch.setattr(retry, "global_values", forbidden)
    monkeypatch.setattr(retry, "bound", forbidden)
    monkeypatch.setattr(module, "per_stock_episodes", forbidden)
    monkeypatch.setattr(module, "daily_candidate_states", forbidden)
    monkeypatch.setattr("research_core.artifact_store.file_digest", forbidden)
    monkeypatch.setattr("research_core.artifact_store.describe_file", forbidden)
    monkeypatch.setattr("research_core.artifact_store.verify_files", forbidden)
    monkeypatch.setattr(module, "_write", write)
    paths = module.run_q4(cast(Any, retry), "B1", candidates, output)
    assert paths == module.completed_results(output)
    assert len(paths) == 6
    for name, (payload, modified) in preserved.items():
        assert (output / name).read_bytes() == payload
        assert (output / name).stat().st_mtime_ns == modified
    expected_coverage = pd.DataFrame([row for row in grouped_coverage(expected_rows) if row["split"] != "all"])
    pd.testing.assert_frame_equal(pd.read_parquet(output / "coverage.parquet").loc[:, expected_coverage.columns], expected_coverage, check_dtype=False)
    pd.testing.assert_frame_equal(pd.read_parquet(output / "draws.parquet"), expected_draws, check_dtype=False)
    pd.testing.assert_frame_equal(pd.read_parquet(output / "quotas.parquet"), expected_quotas, check_dtype=False)
    pd.testing.assert_frame_equal(pd.read_parquet(output / "examples.parquet"), select_q4_examples(expected_rows), check_dtype=False)
    for path in paths:
        pd.testing.assert_frame_equal(pd.read_parquet(path), oracle[path.name], check_exact=True)
    assert not list(output.rglob("*receipt*")) and not list(output.rglob("*manifest*"))


def test_all_complete_retry_never_accesses_inputs_or_reduces_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output = tmp_path / "q4"
    paths = module.run_q4(cast(Any, Inputs()), "B1", {}, output)
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

    class UnavailableInputs:
        def __getattr__(self, name: str) -> Any:
            pytest.fail(f"complete Q4 must not access inputs.{name}")

    def forbidden(*args: object, **kwargs: object) -> Any:
        pytest.fail("complete Q4 must not invoke calculation or writing")

    for name in ("per_stock_episodes", "daily_candidate_states", "grouped_coverage", "select_q4_examples", "_write"):
        monkeypatch.setattr(module, name, forbidden)
    assert module.completed_results(output) == paths
    assert module.run_q4(cast(Any, UnavailableInputs()), "B1", {}, output) == paths
    for path, (payload, modified) in before.items():
        assert path.read_bytes() == payload
        assert path.stat().st_mtime_ns == modified


@pytest.mark.parametrize("damage", ("missing", "corrupt", "schema"))
def test_completed_results_rejects_missing_corrupt_or_wrong_schema_tables(tmp_path: Path, damage: str) -> None:
    output = tmp_path / "q4"
    assert module.completed_results(output) is None
    paths = module.run_q4(cast(Any, Inputs()), "B1", {}, output)
    assert module.completed_results(output) == paths
    path = output / "quotas.parquet"
    if damage == "missing":
        path.unlink()
    elif damage == "corrupt":
        path.write_bytes(b"truncated footer")
    else:
        pd.DataFrame({"unexpected": [1]}).to_parquet(path, index=False)
    assert module.completed_results(output) is None


def test_interrupted_stock_loop_restarts_only_unfinished_stock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class InterruptedInputs(Inputs):
        def stock(self, code: str) -> dict[str, pd.DataFrame]:
            if code == "2330":
                raise OSError("synthetic stock interruption")
            return super().stock(code)

    output = tmp_path / "q4"
    with pytest.raises(OSError, match="synthetic stock interruption"):
        module.run_q4(cast(Any, InterruptedInputs()), "B1", {}, output)
    built: list[str] = []
    episode_builder = module.per_stock_episodes

    def counted_episodes(*args: Any, **kwargs: Any) -> Any:
        built.append(str(args[3]))
        return episode_builder(*args, **kwargs)

    monkeypatch.setattr(module, "per_stock_episodes", counted_episodes)
    assert len(module.run_q4(cast(Any, Inputs()), "B1", {}, output)) == 6
    assert built == ["TW:2330"]


@pytest.mark.parametrize("reader", ("footer", "projection"))
def test_permission_errors_propagate_instead_of_recomputing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reader: str) -> None:
    def denied(*args: object, **kwargs: object) -> Any:
        raise PermissionError("synthetic read permission failure")

    if reader == "footer":
        monkeypatch.setattr(module.pq, "ParquetFile", denied)
        with pytest.raises(PermissionError, match="synthetic read permission"):
            module.completed_results(tmp_path)
    else:
        monkeypatch.setattr(module, "_readable", lambda path, columns: True)
        monkeypatch.setattr(module.pd, "read_parquet", denied)
        with pytest.raises(PermissionError, match="synthetic read permission"):
            module._cached_stock(tmp_path)

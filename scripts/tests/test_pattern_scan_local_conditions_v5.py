"""Bounded Q2/Q3 selection and reductions against the original pure oracles."""

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pandas as pd
import pyarrow.parquet as pq
import pytest

from research_core import pattern_scan_local_conditions_v5 as local
from research_core.artifact_store import read_json, write_json
from research_core.hhhl_variants_selection import Atom, Candidate, DevelopmentCounts, SelectionEvent, SelectionResult, split_for_code
from research_core.pattern_scan_conditions_v1 import FEATURES
from research_core.pattern_scan_local_inputs_v5 import LocalInputs
from research_core.pattern_scan_rates_v1 import summarize_events
from research_core.pattern_scan_reporting_v1 import candidate_membership
from research_core.pattern_scan_selection_v1 import select_pattern_candidates


def _codes(split: str, count: int = 30) -> list[str]:
    return [f"{number:05}" for number in range(1000) if split_for_code(f"{number:05}") == split][:count]


def _frames(events: list[SelectionEvent], atoms: tuple[Atom, ...]) -> local.StockFrames:
    batches: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        row = {
            "event_id": event.event_id,
            "security_id": f"TW:{event.code}",
            "horizon": event.horizon,
            "calendar_full": event.calendar_full,
            "effective_label": event.label,
            "event_main_eligible": event.calendar_full and event.label != "unknown",
        }
        for atom in atoms:
            row[f"{atom.feature_id}_status"] = "known"
            row[f"{atom.feature_id}_bin"] = atom.bin_id if atom in event.atoms else "other"
        batches.setdefault(event.code, []).append(row)
    return lambda: ((code, pd.DataFrame(rows)) for code, rows in sorted(batches.items()))


def test_two_stock_pass_selection_equals_original_for_all_92_candidates() -> None:
    atoms = tuple(Atom(f"family-{index}", f"feature-{index}", "yes") for index in range(9)) + (Atom("K", "diagnostic", "yes"),)
    codes = _codes("development")
    rows = [SelectionEvent(f"base-{index}", codes[index % 30], "union", 126, True, "hit" if index < 61 else "loss", frozenset(atoms)) for index in range(120)]
    rows += [SelectionEvent(f"unknown-{index}", code, "union", 126, True, "unknown", frozenset(atoms)) for index, code in enumerate(codes)]
    rows += [SelectionEvent(f"short-{index}", code, "union", 126, False, "hit", frozenset(atoms)) for index, code in enumerate(codes)]
    rows += [SelectionEvent(f"cross-{index}", code, "union", 126, True, "hit", frozenset(atoms)) for index, code in enumerate(_codes("cross-check"))]
    actual = local.select_streaming("R1", _frames(rows, atoms), atoms)
    expected = select_pattern_candidates("R1", rows, atoms, target_cohorts=("union",))
    assert asdict(actual) == asdict(expected)
    assert len(actual.candidates) == 92
    assert actual.development_counts.known == 120
    assert actual.development_counts.distinct_codes == 30


def test_streaming_thresholds_exact_ties_and_empty_intersections() -> None:
    atoms = (Atom("A", "a", "yes"), Atom("A", "same-family", "yes"), Atom("B", "b", "yes"), Atom("C", "c", "yes"), Atom("D", "below", "yes"))
    codes = _codes("development")
    rows = []
    for number, atom in enumerate(atoms):
        count = 99 if atom.feature_id == "below" else 100
        for index in range(count):
            rows.append(SelectionEvent(f"{number}-{index}", codes[index % 30], "union", 126, True, "hit" if index < 33 else "flat-win", frozenset((atom,))))
    actual = local.select_streaming("R1", _frames(rows, atoms), atoms)
    expected = select_pattern_candidates("R1", rows, atoms, target_cohorts=("union",))
    assert actual == expected
    assert actual.selected_atoms == atoms[:1] + atoms[2:4]
    assert all(candidate.development_counts.known == 0 for candidate in actual.candidates if len(candidate.atoms) > 1)


def test_duplicate_stock_feed_fails_without_collecting_events() -> None:
    atom = Atom("A", "a", "yes")
    code = _codes("development", 1)[0]
    event = SelectionEvent("one", code, "union", 126, True, "hit", frozenset((atom,)))
    batch = list(_frames([event], (atom,))())[0]
    with pytest.raises(ValueError, match="duplicate complete"):
        local.select_streaming("R1", lambda: iter((batch, batch)), (atom,))


def _stock(code: str, horizon: int) -> pd.DataFrame:
    frame = pd.DataFrame({
        "security_id": [f"TW:{code}"] * 5,
        "event_id": [f"{code}-{index}" for index in range(5)],
        "t0": ["2010-01-04", "2011-01-04", "2012-01-04", "2026-01-04", "2026-02-04"],
        "horizon": [horizon] * 5,
        "effective_label": ["hit", "loss", "unknown", "hit", "unknown"],
        "calendar_full": [True, True, True, False, False],
        "event_main_eligible": [True, True, False, False, False],
        "event_eligibility_excluded": [False, False, False, True, False],
        "mkt": ["up", "down", "unknown", "mixed", "consolidation"],
        "MA_b_bin": ["true", "false", None, None, "true"],
        "MA_b_status": ["known", "known", "feature_unknown", "not_applicable", "known"],
    })
    return frame


def test_group_results_preserve_integer_rates_annual_drop_and_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = local.membership_inventory
    monkeypatch.setattr(
        local, "membership_inventory", lambda meta, candidates: tuple(row for row in inventory(meta, candidates) if row["feature_id"] in {"MA_b", "candidate"})
    )
    atom = Atom(FEATURES["MA_b"].family, "MA_b", "true")
    candidate = "pattern-scan.v1:R1:MA_b=true"
    frames = [_stock(_codes(split, 1)[0], 252) for split in ("development", "cross-check")]
    paths, top = local._summarize_group(
        lambda: ((str(frame.security_id.iloc[0])[3:], frame) for frame in frames), "R1", "pattern:union", 252, {candidate: (atom,)}, tmp_path
    )
    summary, annual, coverage = [pd.read_parquet(path) for path in paths]
    assert not summary.feature_id.eq("unconditional").any()
    assert summary.loc[summary.feature_id.eq("candidate"), "split"].eq("cross-check").all()
    complete = pd.concat(frames, ignore_index=True)
    selected = complete.loc[complete.MA_b_status.eq("known") & complete.MA_b_bin.eq("true")]
    where = summary.feature_id.eq("MA_b") & summary.bin_id.eq("true") & summary.split.eq("all") & summary.era.eq("all") & summary.mkt.eq("all")
    full = summary.loc[where & summary.row_kind.eq("full")].iloc[0]
    for name, expected in summarize_events(selected).items():
        assert full[name] == expected or pd.isna(full[name]) and expected is None
    drop = summary.loc[where & summary.row_kind.eq("drop_best_year")].iloc[0]
    assert drop.removed_year == 2010
    assert drop.event_n == 2
    one_annual = annual.loc[annual.feature_id.eq("MA_b") & annual.bin_id.eq("true") & annual.split.eq("all") & annual.era.eq("all") & annual.mkt.eq("all")]
    assert len(one_annual) == 17
    assert one_annual.loc[one_annual.year.eq(2010), "hit_n"].iloc[0] == 2
    assert one_annual.loc[one_annual.year.eq(2026), "unknown_n"].iloc[0] == 2
    unavailable = summary.loc[summary.condition_status.eq("not_applicable")]
    assert unavailable.hit_rate.isna().all()
    own_coverage = coverage.loc[coverage.split.eq("all") & coverage.era.eq("all") & coverage.mkt.eq("all")].iloc[0]
    states = candidate_membership(complete, (atom,))
    for field, value in (("true_n", 1), ("false_n", 0), ("feature_unknown_n", -1), ("not_applicable_n", -2)):
        assert own_coverage[field] == int((states == value).sum())
    assert len(top) == 1 and top[0]["candidate_id"] == candidate
    assert all(pq.ParquetFile(path).metadata.row_group(0).column(0).compression == "ZSTD" for path in paths)


def test_writer_schema_is_stable_when_later_chunks_add_candidate_metadata(tmp_path: Path) -> None:
    path = tmp_path / "result.parquet"
    writer = local._SummaryWriter(path, 1)
    writer.append({"feature_id": "MA_b", "hit_rate": None, "removed_year": None})
    writer.append({"feature_id": "candidate", "candidate_id": "c", "candidate_atoms": [{"feature_id": "MA_b"}], "hit_rate": 0.5, "removed_year": 2010})
    writer.close()
    frame = pd.read_parquet(path)
    assert frame.candidate_id.tolist() == ["", "c"]
    assert frame.hit_rate.iloc[1] == 0.5
    assert frame.candidate_atoms_json.iloc[1] == '[{"feature_id": "MA_b"}]'


def test_target_resume_reuses_selection_and_complete_groups_without_payload_hashes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    inventory = local.membership_inventory
    monkeypatch.setattr(
        local, "membership_inventory", lambda meta, candidates: tuple(row for row in inventory(meta, candidates) if row["feature_id"] in {"MA_b", "candidate"})
    )
    atom = Atom(FEATURES["MA_b"].family, "MA_b", "true")
    identifier = "pattern-scan.v1:R1:MA_b=true"
    selection = SelectionResult((atom,), (Candidate(identifier, (atom,), DevelopmentCounts(61, 39, 0, 30)),), DevelopmentCounts(61, 39, 0, 30))
    selection_calls: list[str] = []

    def select(target: str, frames: local.StockFrames, atoms: tuple[Atom, ...]) -> SelectionResult:
        selection_calls.append(target)
        return selection

    monkeypatch.setattr(local, "select_streaming", select)
    code = _codes("cross-check", 1)[0]
    cache_calls: list[tuple[str, Path]] = []
    inputs = cast(
        LocalInputs,
        SimpleNamespace(
            codes=(code,),
            source_id="original-source",
            input_id="original-input",
            temporary=tmp_path / ".tmp",
            cache_target=lambda target, path: cache_calls.append((target, path)),
            bound=lambda target, stock: SimpleNamespace(daily_groups={"pattern:union": None, "C-secondary": None}),
            group_frame=lambda bound, group, horizon: _stock(code, horizon),
        ),
    )
    summarize = local._summarize_group
    calls: list[tuple[str, int]] = []

    def interrupt(
        frames: local.StockFrames, target: str, group: str, horizon: int, candidates: dict[str, tuple[Atom, ...]], directory: Path
    ) -> tuple[list[Path], list[dict[str, Any]]]:
        calls.append((group, horizon))
        if (group, horizon) == ("pattern:union", 252) and calls.count((group, horizon)) == 1:
            (directory / "unfinished.txt").write_text("owned partial work", encoding="utf-8")
            raise RuntimeError("synthetic interruption")
        return summarize(frames, target, group, horizon, candidates, directory)

    monkeypatch.setattr(local, "_summarize_group", interrupt)
    output = tmp_path / "final"
    with pytest.raises(RuntimeError, match="synthetic interruption"):
        local.run_conditions(inputs, "R1", output)
    progress_path = inputs.temporary / "conditions-progress/R1.json"
    first_progress = read_json(progress_path)
    assert first_progress["selection_complete"] is True
    assert list(first_progress["completed"]) == ["pattern%3Aunion-h126"]
    abandoned = list(output.glob(".staging-pattern%3Aunion-h252-*"))
    assert len(abandoned) == 1 and (abandoned[0] / "unfinished.txt").is_file()
    group_progress: list[tuple[int, int]] = []
    selected, top, paths = local.run_conditions(
        inputs,
        "R1",
        output,
        on_progress=lambda done, total: group_progress.append((done, total)),
    )
    assert selected == asdict(selection)
    assert top == {identifier: (atom,)}
    assert len(paths) == 13 and all(path.is_file() for path in paths)
    assert selection_calls == ["R1"]
    assert calls.count(("pattern:union", 126)) == 1
    assert calls.count(("pattern:union", 252)) == 2
    assert len(read_json(progress_path)["completed"]) == 4
    assert group_progress == [(1, 4), (2, 4), (3, 4), (4, 4)]
    assert abandoned[0].is_dir()
    # A fully complete call does not re-read/reproject any original stock.
    before = len(cache_calls), len(calls)
    assert local.run_conditions(inputs, "R1", output) == (selected, top, paths)
    assert (len(cache_calls), len(calls)) == before
    progress = read_json(progress_path)
    del progress["completed"]["pattern%3Aunion-h252"]
    local._progress(progress_path, progress)
    assert local.run_conditions(inputs, "R1", output) == (selected, top, paths)
    assert len(calls) == before[1]  # Atomic published group is adopted, not redone.
    inputs.input_id = "other-input"
    with pytest.raises(ValueError, match="continuation identity differs"):
        local.run_conditions(inputs, "R1", output)


def test_completed_group_schema_and_narrow_confirmation_read(tmp_path: Path) -> None:
    # A published directory is complete even if interruption precedes progress.
    # Reuse checks table schemas only, never file payload digests.
    directory = tmp_path / "pattern%3Aunion-h252"
    directory.mkdir()
    name = "R1-pattern%3Aunion-h252"
    summary = pd.DataFrame({
        "pattern_id": ["R1"],
        "control_id": ["pattern"],
        "cohort_id": ["union"],
        "horizon": [252],
        "feature_id": ["candidate"],
        "candidate_id": ["c"],
        "condition_status": ["known"],
        "split": ["cross-check"],
        "era": ["all"],
        "mkt": ["all"],
        "known_n": [100],
        "hit_n": [61],
        "row_kind": ["full"],
    })
    summary.to_parquet(directory / f"{name}-summary.parquet", index=False)
    pd.DataFrame({"pattern_id": [], "feature_id": [], "year": [], "event_n": [], "known_n": [], "hit_n": []}).to_parquet(
        directory / f"{name}-annual.parquet", index=False
    )
    pd.DataFrame({
        column: [] for column in ("candidate_id", "split", "era", "mkt", "true_n", "false_n", "feature_unknown_n", "not_applicable_n", "event_n")
    }).to_parquet(directory / f"{name}-candidate-coverage.parquet", index=False)
    paths = local._group_paths(directory, "R1", "pattern:union", 252)
    assert local._confirmation_rows(paths[0])[0]["hit_n"] == 61
    write_json(tmp_path / "existing.json", {"complete": True})
    local._progress(tmp_path / "existing.json", {"complete": False})
    assert read_json(tmp_path / "existing.json") == {"complete": False}

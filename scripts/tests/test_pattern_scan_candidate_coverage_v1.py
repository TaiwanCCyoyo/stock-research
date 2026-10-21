"""Invented conjunction observations retain integer false/unknown/NA coverage."""

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core import pattern_scan_candidate_coverage_v1 as coverage
from research_core.hhhl_variants_selection import Atom, split_for_code
from research_core.pattern_scan_reporting_v1 import candidate_membership, facet_masks

BASE = {"pattern_id": "B1", "control_id": "pattern", "cohort_id": "union", "horizon": 126}
ATOMS = (Atom("MA", "A", "yes"), Atom("VOL", "B", "yes"))
CANDIDATES = {"both": ATOMS, "first": ATOMS[:1]}


def stock_frame(code: str = "0001") -> pd.DataFrame:
    return pd.DataFrame({
        "security_id": f"TW:{code}",
        "event_id": [f"{code}-{i}" for i in range(5)],
        "t0": ["2010-01-04", "2013-01-04", "2019-01-04", "2026-01-04", "2026-02-04"],
        "horizon": 126,
        "mkt": ["up", "unknown", "down", "mixed", "consolidation"],
        "A_bin": ["yes", "no", None, "no", None],
        "A_status": ["known", "known", "feature_unknown", "known", "feature_unknown"],
        "B_bin": ["yes", None, "yes", None, None],
        "B_status": ["known", "feature_unknown", "known", "not_applicable", "not_applicable"],
    })


def overall(table: pd.DataFrame, candidate: str = "both") -> pd.Series:
    return table.loc[table.candidate_id.eq(candidate) & table.split.eq("all") & table.era.eq("all") & table.mkt.eq("all")].iloc[0]


def test_false_absorbs_unknown_and_na_has_priority_without_changing_input() -> None:
    accumulator = coverage.CandidateCoverage(BASE, CANDIDATES)
    source = stock_frame()
    original = source.copy(deep=True)
    accumulator.add_stock(source)
    row = overall(accumulator.finalize())
    assert tuple(row[list(coverage.COUNTS)]) == (1, 1, 1, 2, 5, 1)
    assert candidate_membership(source, ATOMS).tolist() == [1, 0, -1, -2, -2]
    pd.testing.assert_frame_equal(source, original)
    assert accumulator.memory_nbytes == 2 * 72 * len(coverage.COUNTS) * np.dtype("int64").itemsize


def test_every_registered_facet_matches_public_membership_oracle_and_raw_code_crc() -> None:
    source = stock_frame("0050")
    accumulator = coverage.CandidateCoverage(BASE, CANDIDATES)
    accumulator.add_stock(source)
    result = accumulator.finalize()
    assert len(result) == 2 * 72
    for metadata, mask in facet_masks(source):
        for candidate, atoms in CANDIDATES.items():
            row = result.loc[
                result.candidate_id.eq(candidate) & result.split.eq(metadata["split"]) & result.era.eq(metadata["era"]) & result.mkt.eq(metadata["mkt"])
            ].iloc[0]
            values = candidate_membership(source, atoms)[mask]
            assert tuple(row[list(coverage.COUNTS)]) == (
                *[int(np.count_nonzero(values == state)) for state in (1, 0, -1, -2)],
                int(mask.sum()),
                int(mask.any()),
            )
    own_split = result.loc[result.split.eq(split_for_code("0050")) & result.era.eq("all") & result.mkt.eq("all")]
    assert own_split.event_n.eq(5).all()
    other_split = "cross-check" if split_for_code("0050") == "development" else "development"
    assert result.loc[result.split.eq(other_split), "event_n"].eq(0).all()
    assert not any(column.endswith("_rate") for column in result)
    assert all(result[name].dtype == np.dtype("int64") for name in coverage.COUNTS)


def test_independent_stocks_accumulate_observation_counts_instead_of_averaging() -> None:
    accumulator = coverage.CandidateCoverage(BASE, CANDIDATES)
    accumulator.add_stock(stock_frame("0001"))
    accumulator.add_stock(stock_frame("0020").iloc[[0, 2]])
    row = overall(accumulator.finalize())
    assert tuple(row[list(coverage.COUNTS)]) == (2, 1, 2, 2, 7, 2)
    up = accumulator.finalize().loc[lambda table: table.candidate_id.eq("both") & table.split.eq("all") & table.era.eq("all") & table.mkt.eq("up")].iloc[0]
    assert up.event_n == 2 and up.distinct_stock_n == 2


def test_zero_registry_and_no_candidates_keep_explicit_count_schema() -> None:
    zero = coverage.CandidateCoverage(BASE, CANDIDATES).finalize()
    assert len(zero) == 144 and bool(zero[list(coverage.COUNTS)].to_numpy().sum() == 0)
    empty = coverage.CandidateCoverage(BASE, {})
    empty.add_stock(stock_frame())
    result = empty.finalize()
    assert result.empty
    assert list(result.columns) == [*BASE, "candidate_id", *coverage.FACETS, *coverage.COUNTS]
    assert all(result[name].dtype == np.dtype("int64") for name in coverage.COUNTS)


def test_empty_schema_valid_feed_keeps_every_zero_cell() -> None:
    accumulator = coverage.CandidateCoverage(BASE, CANDIDATES)
    before = accumulator.finalize()
    accumulator.add_stock(stock_frame().iloc[:0])
    pd.testing.assert_frame_equal(accumulator.finalize(), before)


@pytest.mark.parametrize(
    "damage",
    [
        "duplicate_event",
        "two_stocks",
        "wrong_horizon",
        "two_horizons",
        "bool_horizon",
        "bad_date",
        "bad_market",
        "missing_condition",
        "bad_status",
        "blank_bin",
        "duplicate_columns",
    ],
)
def test_invalid_feed_rejected_before_mutating_any_candidate_counts(damage: str) -> None:
    accumulator = coverage.CandidateCoverage(BASE, CANDIDATES)
    accumulator.add_stock(stock_frame("0001"))
    before = accumulator.finalize()
    frame = stock_frame("0020")
    if damage == "duplicate_event":
        frame.loc[1, "event_id"] = frame.loc[0, "event_id"]
    elif damage == "two_stocks":
        frame.loc[1, "security_id"] = "TW:3010"
    elif damage == "wrong_horizon":
        frame["horizon"] = 252
    elif damage == "two_horizons":
        frame.loc[1, "horizon"] = 252
    elif damage == "bool_horizon":
        frame["horizon"] = True
    elif damage == "bad_date":
        frame.loc[1, "t0"] = "not-a-date"
    elif damage == "bad_market":
        frame.loc[1, "mkt"] = "all"
    elif damage == "missing_condition":
        frame = frame.drop(columns="B_status")
    elif damage == "bad_status":
        frame.loc[1, "B_status"] = "invalid"
    elif damage == "blank_bin":
        frame.loc[0, "B_bin"] = ""
    else:
        frame = pd.concat([frame, frame[["B_status"]]], axis=1)
    with pytest.raises(ValueError):
        accumulator.add_stock(frame)
    pd.testing.assert_frame_equal(accumulator.finalize(), before)
    accumulator.add_stock(stock_frame("0020"))
    assert overall(accumulator.finalize()).distinct_stock_n == 2


def test_duplicate_stock_feed_rejected_even_with_new_event_ids() -> None:
    accumulator = coverage.CandidateCoverage(BASE, CANDIDATES)
    frame = stock_frame()
    accumulator.add_stock(frame)
    before = accumulator.finalize()
    frame["event_id"] = "again-" + frame.event_id
    with pytest.raises(ValueError, match="duplicate complete stock"):
        accumulator.add_stock(frame)
    pd.testing.assert_frame_equal(accumulator.finalize(), before)


def test_int64_overflow_rejects_all_deltas_before_registering_stock() -> None:
    accumulator = coverage.CandidateCoverage(BASE, CANDIDATES)
    accumulator._counts[:] = coverage.INT64_MAX
    before = accumulator.finalize()
    with pytest.raises(OverflowError, match="int64 overflow"):
        accumulator.add_stock(stock_frame())
    pd.testing.assert_frame_equal(accumulator.finalize(), before)
    accumulator._counts[:] = 0
    accumulator.add_stock(stock_frame())
    assert overall(accumulator.finalize()).event_n == 5


def test_cell_capacity_and_output_field_overrides_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(coverage, "MAX_CELLS", 71)
    with pytest.raises(ValueError, match="cell capacity"):
        coverage.CandidateCoverage(BASE, {"both": ATOMS})
    with pytest.raises(ValueError, match="output field overrides"):
        coverage.CandidateCoverage({**BASE, "true_n": 0}, {})


@pytest.mark.parametrize("candidate", [(), [ATOMS[0]], (ATOMS[0], ATOMS[0]), (Atom("MA", "A", "yes", selectable=False),)])
def test_invalid_or_mutable_candidate_definition_rejected(candidate: Any) -> None:
    with pytest.raises(ValueError):
        coverage.CandidateCoverage(BASE, {"bad": candidate})


def test_caller_metadata_mapping_and_finalized_results_cannot_mutate_accumulator() -> None:
    metadata, candidates = deepcopy(BASE), dict(CANDIDATES)
    accumulator = coverage.CandidateCoverage(metadata, candidates)
    metadata["pattern_id"] = "changed"
    candidates.clear()
    result = accumulator.finalize()
    result["event_n"] = 99
    fresh = accumulator.finalize()
    assert fresh.pattern_id.eq("B1").all() and len(fresh) == 144 and fresh.event_n.eq(0).all()

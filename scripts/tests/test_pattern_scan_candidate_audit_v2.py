"""Synthetic independent candidate audit contracts, no external data readers."""

from __future__ import annotations

import json
import zlib
from dataclasses import asdict
from typing import Any

import pandas as pd
import pytest

from research_core import pattern_scan_candidate_audit_v2 as audit
from research_core.hhhl_variants_selection import Atom

ATOMS = (Atom("MA", "MA_b", "true"), Atom("BB", "BB_c", "true"))


def _events(horizon: int) -> list[pd.DataFrame]:
    # Two original string codes, both in cross-check, including leading zeros.
    codes = [f"{index:04}" for index in range(1, 20) if zlib.crc32(f"{index:04}".encode("utf-8")) % 2 == 1][:2]
    frames = []
    for code in codes:
        rows = []
        for index, (day, label, full, excluded, status_a, bin_a, status_b, bin_b, market) in enumerate((
            ("2011-01-04", "hit", True, False, "known", "true", "known", "true", "up"),
            ("2015-01-05", "hit", True, False, "known", "true", "known", "true", "down"),
            ("2021-01-04", "unknown", True, False, "known", "true", "known", "true", "unknown"),
            ("2021-01-05", "loss", False, False, "known", "true", "known", "true", "unknown"),
            ("2021-01-06", "loss", True, True, "known", "true", "known", "true", "mixed"),
            ("2021-01-07", "flat-win", True, False, "known", "true", "known", "true", "consolidation"),
            ("2021-01-08", "loss", True, False, "known", "false", "feature_unknown", None, "up"),
            ("2021-01-11", "unknown", True, False, "feature_unknown", None, "known", "true", "unknown"),
            ("2021-01-12", "loss", True, False, "known", "false", "not_applicable", None, "down"),
        )):
            rows.append({
                "security_id": f"TW:{code}",
                "event_id": f"control:{code}:{index}",
                "t0": day,
                "horizon": horizon,
                "pattern_id": "C-dip",  # Must not be filtered away by target R1.
                "effective_label": label,
                "calendar_full": full,
                "event_main_eligible": full and not excluded and label != "unknown",
                "event_eligibility_excluded": excluded,
                "mkt": market,
                "MA_b_status": status_a,
                "MA_b_bin": bin_a,
                "BB_c_status": status_b,
                "BB_c_bin": bin_b,
            })
        frames.append(pd.DataFrame(rows))
    return frames


def _rebuild(frames: list[pd.DataFrame], horizon: int) -> dict[str, pd.DataFrame]:
    return audit.reconstruct_candidate(
        frames,
        metadata={
            "pattern_id": "R1",
            "control_id": "C-dip",
            "cohort_id": "union",
            "horizon": horizon,
            "primary_control_id": "C-dip",
        },
        candidate_id="synthetic-conjunction",
        atoms=ATOMS,
    )


@pytest.fixture(scope="module", params=(126, 252))
def reconstructed(request: pytest.FixtureRequest) -> dict[str, pd.DataFrame]:
    return _rebuild(_events(request.param), request.param)


def _row(frame: pd.DataFrame, **fields: Any) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    for name, value in fields.items():
        mask &= frame[name].eq(value)
    selected = frame.loc[mask]
    assert len(selected) == 1
    return selected.iloc[0]


def test_first_five_are_global_sorted_declared_sample_not_ranked_outcomes() -> None:
    def candidate(identifier: str) -> dict[str, Any]:
        return {"candidate_id": identifier, "atoms": [asdict(atom) for atom in ATOMS], "hit_rate": 1.0 if identifier == "z" else 0.0}

    selections = {
        "R1": {"candidates": [candidate("z"), candidate("b"), candidate("a")]},
        "B4": {"candidates": [candidate("c"), candidate("b"), candidate("a")]},
    }
    selected = audit.select_audit_candidates(selections)
    assert [(row["target"], row["candidate_id"]) for row in selected] == [("B4", "a"), ("B4", "b"), ("B4", "c"), ("R1", "a"), ("R1", "b")]
    assert audit.select_audit_candidates({"R1": {"candidates": []}}) == ()
    with pytest.raises(ValueError, match="unique"):
        audit.select_audit_candidates({"R1": {"candidates": [candidate("a"), candidate("a")]}})


@pytest.mark.parametrize(
    "status_a,bin_a,status_b,bin_b,expected",
    (
        ("known", "true", "known", "true", 1),
        ("known", "false", "feature_unknown", None, 0),
        ("feature_unknown", None, "known", "true", -1),
        ("known", "false", "not_applicable", None, -2),
        ("feature_unknown", None, "not_applicable", None, -2),
    ),
)
def test_independent_scalar_precedence(status_a: str, bin_a: str | None, status_b: str, bin_b: str | None, expected: int) -> None:
    assert audit.scalar_membership({"MA_b_status": status_a, "MA_b_bin": bin_a, "BB_c_status": status_b, "BB_c_bin": bin_b}, ATOMS) == expected


@pytest.mark.parametrize("mutation", ("status", "blank", "family", "duplicate", "unselectable"))
def test_scalar_validates_all_atoms_even_after_dominating_na(mutation: str) -> None:
    row = {"MA_b_status": "not_applicable", "MA_b_bin": None, "BB_c_status": "known", "BB_c_bin": "true"}
    atoms = ATOMS
    if mutation == "status":
        row["BB_c_status"] = "invented"
    elif mutation == "blank":
        row["BB_c_bin"] = " "
    elif mutation == "family":
        atoms = (Atom("incorrect", "MA_b", "true"), ATOMS[1])
    elif mutation == "duplicate":
        atoms = (ATOMS[0], ATOMS[0])
    else:
        atoms = (Atom("MA", "MA_b", "true", selectable=False), ATOMS[1])
    with pytest.raises(ValueError, match="status|nonblank|atom"):
        audit.scalar_membership(row, atoms)


def test_full_population_counts_tied_drop_year_facets_and_na_nulls(reconstructed: dict[str, pd.DataFrame]) -> None:
    summary, annual = reconstructed["summary"], reconstructed["annual"]
    assert len(summary) == 3 * 24 * 2 and len(annual) == 3 * 24 * 17
    known = _row(summary, condition_status="known", era="all", mkt="all", row_kind="full")
    assert known.event_n == 12 and known.distinct_stock_n == 2
    assert known.known_n == 6 and known.hit_n == 4 and known.flat_win_n == 2 and known.loss_n == 0
    assert known.unknown_n == known.censored_n == known.excluded_known_n == 2
    assert known.hit_rate == 4 / 6 and known.full_main_potential_n == 8
    assert known.full_calendar_hit_lower_bound == 0.5 and known.full_calendar_hit_upper_bound == 0.75
    dropped = _row(summary, condition_status="known", era="all", mkt="all", row_kind="drop_best_year")
    assert dropped.removed_year == 2011 and dropped.hit_n == 2 and dropped.known_n == 4
    assert _row(annual, condition_status="known", era="all", mkt="all", year=2011).hit_n == 2
    unknown_market = _row(summary, condition_status="known", era="all", mkt="unknown", row_kind="full")
    assert unknown_market.event_n == 4 and unknown_market.known_n == 0
    na = summary.loc[summary.condition_status.eq("not_applicable")]
    assert na.loc[na.era.eq("all") & na.mkt.eq("all") & na.row_kind.eq("full"), "known_n"].iloc[0] == 2
    assert na[[name for name in na if name.endswith("_rate") or name.endswith("_bound")]].isna().all().all()
    na_annual = annual.loc[annual.condition_status.eq("not_applicable")]
    assert na_annual[[name for name in na_annual if name.endswith("_rate") or name.endswith("_bound")]].isna().all().all()
    assert set(reconstructed["memberships"].membership_state) == {1, 0, -1, -2}
    assert reconstructed["memberships"].security_id.str.startswith("TW:0").all()
    assert audit.compare_candidate(reconstructed, stored_summary=summary.copy(), stored_annual=annual.copy())["aggregate_checks"] == 1368


@pytest.mark.parametrize("tamper", ("numerator", "denominator", "atoms", "metadata", "removed_year", "na_null", "missing", "duplicate", "annual"))
def test_intentional_stored_tampering_is_detected(reconstructed: dict[str, pd.DataFrame], tamper: str) -> None:
    summary, annual = reconstructed["summary"].copy(), reconstructed["annual"].copy()
    if tamper in {"numerator", "denominator", "atoms", "metadata", "removed_year", "na_null"}:
        status = "not_applicable" if tamper == "na_null" else "known"
        kind = "drop_best_year" if tamper == "removed_year" else "full"
        index = summary.index[summary.condition_status.eq(status) & summary.era.eq("all") & summary.mkt.eq("all") & summary.row_kind.eq(kind)][0]
        column, value = {
            "numerator": ("hit_n", 999),
            "denominator": ("known_n", 999),
            "atoms": ("candidate_atoms_json", json.dumps([])),
            "metadata": ("primary_control_id", "C-52w"),
            "removed_year": ("removed_year", 2015),
            "na_null": ("hit_rate", 0.0),
        }[tamper]
        summary.at[index, column] = value
    elif tamper == "missing":
        summary = summary.iloc[1:].copy()
    elif tamper == "duplicate":
        summary = pd.concat([summary, summary.iloc[:1]], ignore_index=True)
    else:
        annual.at[0, "event_n"] += 1
    with pytest.raises(ValueError, match="mismatch|metadata|duplicate|missing"):
        audit.compare_candidate(reconstructed, stored_summary=summary, stored_annual=annual)


def test_float_tolerance_and_exact_integer_contract(reconstructed: dict[str, pd.DataFrame]) -> None:
    summary, annual = reconstructed["summary"].copy(), reconstructed["annual"].copy()
    index = summary.index[summary.condition_status.eq("known") & summary.era.eq("all") & summary.mkt.eq("all") & summary.row_kind.eq("full")][0]
    summary.at[index, "hit_rate"] += 5e-13
    audit.compare_candidate(reconstructed, stored_summary=summary, stored_annual=annual)
    summary.at[index, "hit_rate"] += 1e-6
    with pytest.raises(ValueError, match="hit_rate"):
        audit.compare_candidate(reconstructed, stored_summary=summary, stored_annual=annual)
    summary = reconstructed["summary"].copy()
    summary["hit_n"] = summary.hit_n.astype(float)
    with pytest.raises(ValueError, match="hit_n"):
        audit.compare_candidate(reconstructed, stored_summary=summary, stored_annual=annual)


def test_explicit_empty_population_keeps_all_zero_cells_and_null_drop_year() -> None:
    empty = _rebuild([frame.iloc[:0] for frame in _events(126)], 126)
    assert len(empty["summary"]) == 144 and len(empty["annual"]) == 1224
    assert empty["summary"].event_n.eq(0).all() and empty["annual"].event_n.eq(0).all()
    assert empty["summary"].removed_year.isna().all()
    assert empty["summary"].hit_rate.isna().all()
    assert empty["memberships"].empty
    audit.compare_candidate(empty, stored_summary=empty["summary"], stored_annual=empty["annual"])


def test_development_rows_are_recorded_but_excluded_from_candidate_summaries() -> None:
    code = next(f"{index:04}" for index in range(1, 20) if zlib.crc32(f"{index:04}".encode("utf-8")) % 2 == 0)
    frame = _events(126)[0].copy()
    frame["security_id"] = f"TW{code}"
    result = _rebuild([frame], 126)
    assert result["memberships"].split.eq("development").all()
    assert result["summary"].event_n.eq(0).all()

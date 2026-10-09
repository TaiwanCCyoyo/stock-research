from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.method_environment_interactions import _triage, analyze, attach_context


def frame(size: int = 8) -> pd.DataFrame:
    result = pd.DataFrame({
        "security_id": [f"TW:{i}" for i in range(size)],
        "asof_date": pd.Timestamp("2020-01-02"),
        "calendar_index": 126,
        "year": 2020,
        "base_eligible": True,
        "market_state": "up",
        "F10": 1.0,
        "F32": 1.0,
        "F33": 1.0,
        "F37": 1.0,
    })
    for horizon in (63, 126):
        result[f"label_{horizon}"] = 1.0
        result[f"complete_{horizon}"] = True
        result[f"forward_return_{horizon}"] = horizon / 100
        result[f"min_return_{horizon}"] = -0.2
        result[f"max_drawdown_{horizon}"] = 0.3
        result[f"wait_to_threshold_{horizon}"] = 10.0
    return result


def context(**changes: Any) -> dict[str, Any]:
    return {
        "security_id": "TW:0050",
        "asof_date": "2020-01-02",
        "layer": "past_only",
        "state": "up",
        "information_cutoff": "2020-01-02",
        "missing_reason": None,
        **changes,
    }


def pooled(output: dict[str, Any], arm: str = "method", family: str = "F10", panel: str = "daily", label: str = "label_126") -> dict[str, Any]:
    return next(
        row
        for row in output["comparisons"]
        if row["family"] == family and row["panel"] == panel and row["arm"] == arm and row["label"] == label and row["context_column"] is None
    )


def test_common_support_confusion_cells_denominators_and_unknown_bounds() -> None:
    data = frame()
    data["F10"] = [1, 1, 0, 0, 1, None, 0, 1]
    data["F37"] = [1, 0, 1, 0, 1, 0, None, 1]
    data["label_126"] = [1, 0, 1, 0, None, 1, 0, 1]
    data.loc[7, "base_eligible"] = False
    data.loc[4, "complete_126"] = False
    output = analyze(data)
    row = pooled(output)
    assert [row[key] for key in ("tp", "fp", "fn", "tn")] == [1, 1, 1, 1]
    assert row["n_eligible"] == 7
    for arm in ("all", "method", "relative_strength", "conjunction"):
        candidate = pooled(output, arm)
        assert candidate["n_feature_missing"] == 2
        assert candidate["n_feature_known"] == 5
        assert candidate["same_context_base_rate"] == 0.5
    assert row["precision_lower"] == pytest.approx(1 / 3)
    assert row["precision_upper"] == pytest.approx(2 / 3)
    assert row["selected_distinct_issuers"] == 2
    assert row["n_distinct_securities"] == 7
    json.dumps(output, allow_nan=False)


def test_path_nonwinner_attribution_matching_horizon_and_wait_only_winners() -> None:
    data = frame(3)
    data["label_126"] = [1, 0, None]
    data.loc[2, "complete_126"] = False
    data["forward_return_126"] = [2.0, 0.1, 99.0]
    data["min_return_126"] = [-0.1, -0.5, -99.0]
    data.loc[1, "max_drawdown_126"] = np.nan
    data["wait_to_threshold_126"] = [5.0, 0.0, 99.0]
    output = analyze(data)
    rows = {
        r["outcome"]: r
        for r in output["path_summaries"]
        if r["panel"] == "daily" and r["family"] == "F10" and r["arm"] == "method" and r["label"] == "label_126" and r["context_column"] is None
    }
    assert rows["all"]["selected_known"] == 2
    assert rows["all"]["metrics"]["forward_return"]["mean"] == 1.05
    assert rows["nonwinner"]["metrics"]["min_return"]["median"] == -0.5
    assert rows["nonwinner"]["metrics"]["max_drawdown"]["missing"] == 1
    assert "wait_to_threshold" not in rows["nonwinner"]["metrics"]
    assert "wait_to_threshold" not in rows["all"]["metrics"]
    assert rows["winner"]["metrics"]["wait_to_threshold"]["count"] == 1
    assert rows["winner"]["metrics"]["wait_to_threshold"]["mean"] == 5
    secondary = next(
        r
        for r in output["path_summaries"]
        if r["panel"] == "daily"
        and r["family"] == "F10"
        and r["arm"] == "method"
        and r["label"] == "label_63"
        and r["context_column"] is None
        and r["outcome"] == "all"
    )
    assert secondary["metrics"]["forward_return"]["mean"] == pytest.approx(0.63)


def test_original_grid_and_separate_context_dimensions() -> None:
    data = frame(3)
    data["asof_date"] = pd.to_datetime(["2020-01-02", "2020-01-03", "2021-01-04"])
    data["year"] = [2020, 2020, 2021]
    data["calendar_index"] = [125, 126, 252]
    data["base_eligible"] = [True, False, True]
    data["market_state"] = ["unknown", "down", "mixed"]
    output = analyze(data)
    assert pooled(output, panel="daily")["n_eligible"] == 2
    assert pooled(output, panel="grid126")["n_eligible"] == 1
    assert {r["context_column"] for r in output["comparisons"]} == {None, "market_state", "year"}
    assert any(r["context_value"] == "unknown" for r in output["comparisons"])
    assert pooled(output, panel="grid126")["selected_distinct_dates"] == 1


def test_left_context_join_missing_dates_and_unknown_reason_preserves_index() -> None:
    data = frame(2).drop(columns="market_state")
    data.index = [4, 9]
    data.loc[9, "asof_date"] = pd.Timestamp("2020-01-03")
    data.loc[9, "calendar_index"] = 127
    joined, audit = attach_context(data, [context(state="unknown", missing_reason="warmup")])
    assert joined.index.tolist() == [4, 9]
    assert len(joined) == len(data)
    assert joined.market_state.tolist() == ["unknown", "unknown"]
    assert joined.context_missing_reason.tolist() == ["warmup", "missing_context_date"]
    assert audit["missing_context_dates"] == audit["missing_context_rows"] == 1
    assert audit["unknown_context_rows"] == 2
    empty, empty_audit = attach_context(data, [])
    assert empty.context_missing_reason.eq("missing_context_date").all()
    assert empty_audit["missing_context_rows"] == 2


@pytest.mark.parametrize(
    "rows,match",
    [
        ([context(), context()], "duplicate context"),
        ([context(security_id="TW:2330")], "TW:0050"),
        ([context(layer="retrospective")], "past_only"),
        ([context(information_cutoff="2020-01-03")], "future"),
        ([context(asof_date="01/02/2020")], "ISO"),
        ([context(information_cutoff=None)], "nonmissing"),
        ([context(state="invalid")], "state"),
    ],
)
def test_context_fails_closed(rows: list[dict[str, Any]], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        attach_context(frame().drop(columns="market_state"), rows)


@pytest.mark.parametrize(
    "column,value,match",
    [
        ("F10", 2, "F10"),
        ("label_63", -1, "label_63"),
        ("base_eligible", "true", "base_eligible"),
        ("complete_126", False, "complete path"),
        ("calendar_index", 1.5, "integers"),
        ("year", 2019, "year"),
    ],
)
def test_analysis_rejects_invalid_flags_and_calendar(column: str, value: Any, match: str) -> None:
    data = frame(1)
    data[column] = value
    with pytest.raises(ValueError, match=match):
        analyze(data)


def test_duplicate_keys_and_inconsistent_calendar_mapping() -> None:
    data = frame(2)
    data.loc[1, "security_id"] = data.loc[0, "security_id"]
    with pytest.raises(ValueError, match="duplicate"):
        analyze(data)
    data = frame(2)
    data.loc[1, "calendar_index"] = 127
    with pytest.raises(ValueError, match="mapping"):
        analyze(data)
    data.loc[1, "asof_date"] = pd.Timestamp("2020-01-03")
    data.loc[1, "calendar_index"] = 125
    with pytest.raises(ValueError, match="order"):
        analyze(data)


def qualifying_comparisons(years: int = 4) -> list[dict[str, Any]]:
    rows = []
    for family in ("F10", "F32", "F33"):
        for arm in ("method", "relative_strength", "conjunction"):
            for panel in ("daily", "grid126"):
                for year in [None, *range(2019, 2019 + years)]:
                    rows.append({
                        "panel": panel,
                        "family": family,
                        "arm": arm,
                        "label": "label_126",
                        "context_column": "year" if year else None,
                        "context_value": year,
                        "selected_known": 40,
                        "selected_distinct_issuers": 10,
                        "precision": 0.4 if arm == "relative_strength" else 0.6,
                        "tp": 20 if arm == "relative_strength" else 5,
                        "selected_unknown": 2,
                        "precision_lower": 0.3,
                        "precision_upper": 0.7,
                    })
    return rows


def test_triage_exact_retention_support_boundaries_and_fixed_tie_break() -> None:
    rows = qualifying_comparisons()
    output = _triage(rows)
    assert all(row["qualifies"] for row in output["candidates"])
    assert output["nomination"]["family"] == "F10"
    assert output["nomination"]["arm"] == "method"
    assert output["nomination"]["minimum_winner_retention"] == 0.25
    rows[0]["selected_known"] = 29
    assert not _triage(rows)["candidates"][0]["qualifies"]
    rows[0]["selected_known"] = 30
    rows[0]["selected_distinct_issuers"] = 9
    assert not _triage(rows)["candidates"][0]["qualifies"]
    rows[0]["selected_distinct_issuers"] = 10
    for row in rows:
        if row["family"] == "F10" and row["arm"] == "conjunction" and row["panel"] == "daily" and row["context_column"] is None:
            row["tp"] = 4
    assert not _triage(rows)["candidates"][0]["qualifies"]


def test_triage_annual_strict_majority_excludes_2026_and_diagnostic_rescue() -> None:
    rows = qualifying_comparisons()
    for row in rows:
        if row["arm"] != "relative_strength" and row["context_value"] in (2019, 2020):
            row["precision"] = 0.4
    assert _triage(rows)["nomination"] is None  # two wins out of four is not a majority
    rows.extend({**r, "context_value": 2026} for r in list(rows) if r["context_value"] == 2022)
    assert _triage(rows)["nomination"] is None
    for row in rows:
        if row["context_value"] == 2019 and row["arm"] != "relative_strength":
            row["precision"] = 0.6
    assert _triage(rows)["nomination"] is not None
    for row in rows:
        if row["context_value"] == 2022:
            row["selected_known"] = 29
    assert _triage(rows)["nomination"] is None


def test_triage_larger_minimum_retention_precedes_family_and_zero_control_is_null() -> None:
    rows = qualifying_comparisons()
    for row in rows:
        if row["family"] == "F33" and row["arm"] == "conjunction":
            row["tp"] = 6
    assert _triage(rows)["nomination"]["family"] == "F33"
    for row in rows:
        if row["arm"] == "relative_strength":
            row["tp"] = 0
    output = _triage(rows)
    assert output["nomination"] is None
    assert all(r["minimum_winner_retention"] is None for r in output["candidates"])
    data = frame(1)
    data["label_126"] = 0.0
    output = analyze(data)
    assert all(r["winner_retention"] is None for r in output["paired_rows"] if r["label"] == "label_126")


def test_nomination_carries_nonwinner_paths_and_unknown_bounds() -> None:
    data = pd.concat(
        [frame(40).assign(asof_date=pd.Timestamp(f"{year}-01-02"), year=year, calendar_index=i * 126) for i, year in enumerate(range(2019, 2023))],
        ignore_index=True,
    )
    data["F10"] = np.tile([1.0] * 30 + [0.0] * 10, 4)
    data["label_126"] = np.tile([1.0] * 20 + [0.0] * 20, 4)
    output = analyze(data)
    nominee = output["triage"]["nomination"]
    assert nominee["family"] == "F10" and nominee["arm"] == "method"
    assert len(nominee["nonwinner_paths"]) == len(nominee["pooled_unknown_label_bounds"]) == 2
    assert all(row["selected_known"] == 40 for row in nominee["nonwinner_paths"])
    paired = next(
        r
        for r in output["paired_rows"]
        if r["family"] == "F10"
        and r["arm"] == "conjunction"
        and r["control"] == "relative_strength"
        and r["context_column"] is None
        and r["panel"] == "daily"
        and r["label"] == "label_126"
    )
    assert paired["differences"]["precision"] == pytest.approx(1 / 6)
    assert paired["winner_retention"] == 1
    json.dumps(output, allow_nan=False)


@pytest.mark.parametrize(
    "rs_flags,intersection,rs_winners",
    [
        ([0.0, 0.0, 0.0, 1.0, 1.0, 0.0], 0, 2),
        ([1.0, 0.0, 0.0, 1.0, 1.0, 0.0], 1, 3),
    ],
)
def test_paired_retention_uses_actual_winner_intersection(rs_flags: list[float], intersection: int, rs_winners: int) -> None:
    data = frame(6)
    data["F10"] = [1.0, 1.0, 1.0, 0.0, 0.0, 0.0]
    data["F37"] = rs_flags
    output = analyze(data)
    paired = {
        (r["arm"], r["control"]): r
        for r in output["paired_rows"]
        if r["family"] == "F10" and r["panel"] == "daily" and r["label"] == "label_126" and r["context_column"] is None
    }
    method_rs = paired[("method", "relative_strength")]
    assert method_rs["candidate_tp"] == 3
    assert method_rs["control_tp"] == rs_winners
    assert method_rs["retained_winners"] == intersection
    assert method_rs["winner_retention"] == intersection / rs_winners
    assert paired[("relative_strength", "method")]["winner_retention"] == intersection / 3
    assert paired[("conjunction", "relative_strength")]["winner_retention"] == intersection / rs_winners
    assert paired[("conjunction", "method")]["winner_retention"] == intersection / 3
    assert paired[("all", "method")]["winner_retention"] == 1
    assert paired[("all", "relative_strength")]["winner_retention"] == 1
    assert all(0 <= r["winner_retention"] <= 1 for r in paired.values())


def test_triage_method_requires_retention_of_rs_winners_not_whole_candidate_tp() -> None:
    rows = qualifying_comparisons()
    for row in rows:
        if row["arm"] == "method":
            row["tp"] = 30  # total method winners cannot rescue disjoint RS winners
        elif row["arm"] == "conjunction":
            row["tp"] = 0
    output = _triage(rows)
    assert output["nomination"] is None
    assert all(r["minimum_winner_retention"] == 0 for r in output["candidates"])
    for row in rows:
        if row["family"] == "F10" and row["arm"] == "conjunction":
            row["tp"] = 5  # exactly 25 percent of 20 RS winners
    output = _triage(rows)
    assert output["nomination"]["family"] == "F10"
    assert output["nomination"]["arm"] == "method"
    candidate = output["candidates"][0]
    assert candidate["minimum_winner_retention"] == 0.25
    assert candidate["panels"]["daily"]["candidate_tp"] == 30
    assert candidate["panels"]["daily"]["retained_winners"] == 5

"""Differential unconditional Q1 counts without market data or IO."""

import math
from typing import cast

import pandas as pd
import pytest

from research_core.pattern_scan_q1_counts_v1 import Q1Counts
from research_core.pattern_scan_rates_v1 import drop_best_hit_year, summarize_events
from research_core.pattern_scan_reporting_v1 import facet_masks
from research_core.pattern_scan_summary_store_v1 import YEARS


def feed(code: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    rows = []
    observations: tuple[tuple[str, str, bool, bool, bool], ...] = (
        ("2010-01-04", "hit", True, True, False),
        ("2011-01-04", "hit" if code == "0050" else "loss", True, True, False),
        ("2013-01-04", "unknown", True, False, False),
        ("2019-01-04", "unknown", False, False, False),
        ("2020-01-06", "hit", False, False, True),
        ("2021-01-04", "loss", True, False, True),
    )
    if code == "2330":
        observations += (("2014-01-06", "loss", True, True, False),)
    for index, (day, label, full, eligible, excluded) in enumerate(observations):
        for horizon in (126, 252):
            rows.append({
                "security_id": f"TW:{code}",
                "event_id": f"{code}-{index}",
                "t0": day,
                "horizon": horizon,
                "effective_label": label,
                "calendar_full": full,
                "event_main_eligible": eligible,
                "event_eligibility_excluded": excluded,
            })
    events = pd.DataFrame(rows)
    memberships = pd.DataFrame({"group_id": "pattern:union", "event_id": events.event_id.drop_duplicates().to_numpy()})
    markets = pd.Series(["up", "down", "mixed"], index=["2010-01-04", "2011-01-04", "2013-01-04"])
    return events, memberships, markets


def assert_summary(row: pd.Series, expected: dict[str, int | float | None]) -> None:
    for name, value in expected.items():
        actual = cast(int | float | None, row[name])
        if value is None:
            assert actual is None or math.isnan(float(actual)), (name, actual, value)
        else:
            assert actual == value, (name, actual, value)


def test_all_facets_differential_integer_counts_years_and_zero_cells() -> None:
    counts = Q1Counts("H1", ("pattern:union", "C-base-all"))
    masks: dict[tuple[int, str, str, str], list[pd.DataFrame]] = {}
    for code in ("0050", "2330"):
        events, memberships, markets = feed(code)
        counts.add_stock(code, events, memberships, markets=markets)
        for horizon in (126, 252):
            frame = events.loc[events.horizon.eq(horizon)].copy()
            frame["mkt"] = frame.t0.map(markets).fillna("unknown")
            for facets, mask in facet_masks(frame):
                key = horizon, facets["split"], facets["era"], facets["mkt"]
                masks.setdefault(key, []).append(frame.loc[mask])
    summary, annual = counts.finalize()
    assert len(summary) == 2 * 2 * 72 * 2
    assert len(annual) == 2 * 2 * 72 * 17
    for (horizon, split, era, market), frames in masks.items():
        joined = pd.concat(frames, ignore_index=True)
        selection = summary.loc[
            summary.control_id.eq("pattern") & summary.horizon.eq(horizon) & summary.split.eq(split) & summary.era.eq(era) & summary.mkt.eq(market)
        ]
        assert_summary(selection.loc[selection.row_kind.eq("full")].iloc[0], summarize_events(joined))
        removed, dropped = drop_best_hit_year(joined)
        drop = selection.loc[selection.row_kind.eq("drop_best_year")].iloc[0]
        assert_summary(drop, dropped)
        assert pd.isna(drop.removed_year) if removed is None else drop.removed_year == removed
        yearly = annual.loc[
            annual.control_id.eq("pattern") & annual.horizon.eq(horizon) & annual.split.eq(split) & annual.era.eq(era) & annual.mkt.eq(market)
        ].set_index("year")
        for year in YEARS:
            assert_summary(yearly.loc[year], summarize_events(joined.loc[joined.t0.str[:4].eq(str(year))]))
    assert summary.loc[summary.control_id.eq("C-base-all"), "event_n"].eq(0).all()
    full = summary.loc[summary.control_id.eq("pattern") & summary.horizon.eq(126) & summary.split.eq("all") & summary.era.eq("all") & summary.mkt.eq("all")]
    assert full.loc[full.row_kind.eq("full"), "hit_n"].iloc[0] == 3
    assert full.loc[full.row_kind.eq("full"), "hit_rate"].iloc[0] == 3 / 5
    assert full.loc[full.row_kind.eq("drop_best_year"), "removed_year"].iloc[0] == 2010
    assert counts.memory_nbytes > 0
    reversed_counts = Q1Counts("H1", ("pattern:union", "C-base-all"))
    for code in ("2330", "0050"):
        events, memberships, markets = feed(code)
        reversed_counts.add_stock(code, events, memberships, markets=markets)
    reverse_summary, reverse_annual = reversed_counts.finalize()
    pd.testing.assert_frame_equal(summary, reverse_summary)
    pd.testing.assert_frame_equal(annual, reverse_annual)


@pytest.mark.parametrize("mutation", ["missing_event", "missing_horizon", "duplicate", "unknown_group", "wrong_stock", "bad_market"])
def test_reject_malformed_feed_without_consuming_stock(mutation: str) -> None:
    counts = Q1Counts("H1", ("pattern:union",))
    events, memberships, markets = feed("0050")
    if mutation == "missing_event":
        memberships.loc[0, "event_id"] = "absent"
    elif mutation == "missing_horizon":
        events = events.iloc[1:]
    elif mutation == "duplicate":
        memberships = pd.concat([memberships, memberships.iloc[:1]], ignore_index=True)
    elif mutation == "unknown_group":
        memberships.loc[0, "group_id"] = "pattern:imaginary"
    elif mutation == "wrong_stock":
        events.loc[0, "security_id"] = "TW:2330"
    else:
        markets.iloc[0] = "invalid"
    with pytest.raises(ValueError):
        counts.add_stock("0050", events, memberships, markets=markets)
    valid = feed("0050")
    counts.add_stock("0050", valid[0], valid[1], markets=valid[2])
    with pytest.raises(ValueError, match="duplicate stock"):
        counts.add_stock("TW:0050", valid[0], valid[1], markets=valid[2])


@pytest.mark.parametrize("target,groups", [("fake", ("pattern:union",)), ("H1", ("pattern:fake",)), ("L1", ("pattern:P-clean",)), ("H1", ())])
def test_reject_unregistered_scope(target: str, groups: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        Q1Counts(target, groups)


def test_empty_stock_duplicate_is_rejected_and_zero_inventory_retained() -> None:
    counts = Q1Counts("H1", ("pattern:union",))
    events, memberships, markets = feed("0050")
    counts.add_stock("0050", events.iloc[:0], memberships.iloc[:0], markets=markets)
    with pytest.raises(ValueError, match="duplicate stock"):
        counts.add_stock("0050", events.iloc[:0], memberships.iloc[:0], markets=markets)
    summary, annual = counts.finalize()
    assert summary.event_n.eq(0).all() and len(annual) == 2 * 72 * 17

"""Pure Q4 admission, uncertainty and control-quota contracts."""

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_episode_coverage_v1 import CONTROL_COLUMNS
from research_core.pattern_scan_episode_tables_v1 import (
    admission_counts,
    daily_base_coverage,
    grouped_coverage,
    observe_group,
    per_stock_episodes,
    random_control_coverage,
    summarize_coverage,
)


def calendar(size: int = 220) -> list[str]:
    return pd.date_range("2010-01-04", periods=size).strftime("%Y-%m-%d").tolist()


def labels(starts: tuple[int, ...]) -> pd.DataFrame:
    return pd.DataFrame({"calendar_index": list(starts), "horizon": [126] * len(starts), "label": ["hit"] * len(starts), "calendar_full": [True] * len(starts)})


def test_admission_chain_anchor_and_peak_ties_and_no_s6_gate() -> None:
    closes = [100.0] * 220
    closes[50] = closes[70] = 90
    closes[90] = 95
    closes[100] = closes[110] = 200
    base = labels((50, 70, 90))
    base["base_eligible"] = False
    before = base.copy(deep=True)
    episodes, admitted = per_stock_episodes(closes, base, [None] * 220, "0050", dates=calendar())
    assert len(episodes) == 1 and episodes[0].start_indices == (50, 70, 90)
    assert episodes[0].anchor_index == 50 and episodes[0].peak_index == 100
    assert admission_counts(admitted) == {"start_n": 3, "admitted_n": 3, "excluded_n": 0, "exclusion_counts": {}}
    pd.testing.assert_frame_equal(base, before)


def test_jump_after_first_hit_excludes_entire_result_start_but_missing_peak_retains() -> None:
    closes = [100.0] * 220
    closes[55] = 200
    quality: list[str | None] = [None] * 220
    quality[80] = "unexplained_adjusted_jump"
    episodes, admitted = per_stock_episodes(closes, labels((50,)), quality, "0050", dates=calendar())
    assert episodes == ()
    assert admitted.iloc[0].exclusion_reasons == ("result_window_unexplained_jump",)
    closes[80] = float("nan")
    quality[80] = "missing_price"
    episodes, admitted = per_stock_episodes(closes, labels((50,)), quality, "0050", dates=calendar())
    assert admitted.iloc[0].admitted
    assert episodes[0].anchor_index == 50 and episodes[0].peak_index is None and episodes[0].status == "unknown"


def test_unknown_absorption_all_matches_and_independent_quantile_counts() -> None:
    closes = [100.0] * 220
    closes[80] = float("nan")
    episodes, _ = per_stock_episodes(closes, labels((50,)), [None] * 220, "0050", dates=calendar())
    states = [0] * 220
    states[31], states[60], states[70] = -1, 1, 1
    rows = observe_group(episodes, closes, calendar(), [70, 60], states, ["up"] * 220, "0050", "P1")
    assert rows.iloc[0].matching_indices == (60, 70)
    assert rows.iloc[0].coverage_status == "matched"
    assert not rows.iloc[0].first_timing_certain
    result = summarize_coverage(rows)
    assert result["matched_n"] == 1 and result["coverage_rate"] == 1
    assert result["timing_known_n"] == 0 and result["timing_unknown_n"] == 1
    assert result["entry_return_known_n"] == 1 and result["remaining_return_known_n"] == 0
    facets = list(grouped_coverage(rows))
    assert len(facets) == 72
    assert facets[0]["episode_n"] == 1
    assert next(row for row in facets if (row["split"], row["era"], row["mkt"]) == ("all", "all", "unknown"))["episode_n"] == 0


def test_random_shortfall_keeps_observed_matches_but_effective_coverage_unknown() -> None:
    closes = [100.0] * 220
    episodes, _ = per_stock_episodes(closes, labels((50,)), [None] * 220, "0050", dates=calendar())
    dates = calendar()
    pool = pd.DataFrame([("0050", 60, dates[60])], columns=pd.Index(CONTROL_COLUMNS))
    target = pd.DataFrame([("0050", 60, dates[60]), ("0050", 100, dates[100])], columns=pd.Index(CONTROL_COLUMNS))
    rows, drawn, quota = random_control_coverage(
        pool,
        target,
        group_id="P1-random",
        episodes=episodes,
        closes=closes,
        dates=dates,
        anchor_regime=["mixed"] * 220,
        security_id="0050",
        pool_pin="immutable-pool-v1",
    )
    assert rows.iloc[0].observed_coverage_status == "matched"
    assert rows.iloc[0].coverage_status == "unknown" and rows.iloc[0].quota_shortfall
    assert rows.iloc[0].matching_indices == (60,)
    assert len(drawn) == 1 and quota.iloc[0].shortfall_n == 1
    assert quota.iloc[0].pool_pin == "immutable-pool-v1"
    result = summarize_coverage(rows)
    assert result["matched_n"] == 0 and result["unknown_n"] == 1
    assert result["coverage_rate"] is None
    assert result["coverage_lower_bound"] == 0 and result["coverage_upper_bound"] == 1


def test_daily_base_is_distinct_and_keeps_adjacent_candidates() -> None:
    closes = [100.0] * 220
    episodes, _ = per_stock_episodes(closes, labels((50,)), [None] * 220, "0050", dates=calendar())
    states = [0] * 220
    states[60] = states[61] = 1
    rows = daily_base_coverage(episodes, closes, calendar(), states, ["unknown"] * 220, "0050")
    assert rows.iloc[0].group_id == "C-base-all"
    assert rows.iloc[0].matching_indices == (60, 61)


def test_admission_empty_schema_and_nonhit_censored_reasons() -> None:
    base = labels((50, 51, 52))
    base.loc[0, "label"] = "loss"
    base.loc[1, "label"] = "unknown"
    base.loc[2, "calendar_full"] = False
    episodes, admitted = per_stock_episodes([100.0] * 220, base, [None] * 220, "0050", dates=calendar())
    assert episodes == ()
    assert admission_counts(admitted)["excluded_n"] == 3
    empty_episodes, empty_admissions = per_stock_episodes([100.0] * 220, base.iloc[:0], [None] * 220, "0050", dates=calendar())
    assert empty_episodes == () and admission_counts(empty_admissions)["start_n"] == 0
    rows = observe_group((), [100.0] * 220, calendar(), [], [0] * 220, ["unknown"] * 220, "0050", "P1")
    assert rows.empty and summarize_coverage(rows)["coverage_rate"] is None
    assert list(grouped_coverage(rows)) == []


def test_base_label_alias_consistency_and_calendar_alignment() -> None:
    base = labels((50,)).rename(columns={"label": "base_label"})
    episodes, _ = per_stock_episodes([100.0] * 220, base, [None] * 220, "0050", dates=calendar())
    assert len(episodes) == 1
    base["label"] = "loss"
    with pytest.raises(ValueError, match="disagree"):
        per_stock_episodes([100.0] * 220, base, [None] * 220, "0050", dates=calendar())
    with pytest.raises(ValueError, match="align"):
        per_stock_episodes([100.0] * 220, labels((50,)), [None] * 219, "0050", dates=calendar())


def test_known_quantile_uses_certain_first_offset_and_late_peak() -> None:
    closes = [100.0] * 220
    closes[55] = 200
    episodes, _ = per_stock_episodes(closes, labels((50,)), [None] * 220, "0050", dates=calendar())
    states = np.zeros(220, dtype=np.int8)
    states[60] = 1
    rows = observe_group(episodes, closes, calendar(), [60], states.tolist(), ["up"] * 220, "0050", "P1")
    result = summarize_coverage(rows)
    assert result["timing_median"] == result["timing_q25"] == result["timing_q75"] == 10
    assert result["remaining_return_median"] == 1
    assert result["late_n"] == 1

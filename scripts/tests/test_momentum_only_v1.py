from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research_core import momentum_only_v1 as study
from research_core.hhhl_variants_paths import outcomes_for_closes
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_projection_v1 import project_outcomes
from research_core.pattern_scan_rates_v1 import summarize_events


def test_mission_fixes_22_pure_momentum_sets() -> None:
    sets = study.condition_sets()
    assert len(sets) == 22
    assert sets["A1&A2"] == ("A1", "A2") and sets["LEAD_B1"] == ("A1", "A2", "A3")
    assert all("A7" not in atoms for atoms in sets.values()), "pattern-involved sets are not pure momentum"


@pytest.mark.parametrize("lookback", [0, 250])
def test_quality_windows_match_the_pr17_projection(lookback: int) -> None:
    n, horizon = 600, 126
    jump = np.zeros(n, dtype=bool)
    jump[[5, 300, 599]] = True
    quality = study.quality_unknown(jump, lookback, horizon)
    expected = np.array([jump[max(0, i - lookback) : i + 1].any() or jump[i + 1 : min(i + horizon, n - 1) + 1].any() for i in range(n)])
    assert np.array_equal(quality, expected)


def _synthetic(n: int = 520, seed: int = 3) -> tuple[study.StockDaily, pd.Series, np.ndarray]:
    rng = np.random.default_rng(seed)
    close = 20 * np.exp(np.cumsum(rng.normal(0.002, 0.03, n)))
    close[[100, 101]] = np.nan
    dates = pd.bdate_range("2015-01-05", periods=n)
    reasons = pd.Series([None] * n, index=dates, dtype=object)
    reasons.iloc[[40, 260]] = "unexplained_jump"
    reasons.iloc[100] = "missing_official_quote"
    eligible = rng.random(n) > 0.2
    labels, main, full = {}, {}, {}
    for horizon in study.HORIZONS:
        for target in study.TARGETS:
            from research_core.multiple_outcomes_v1 import outcomes_for_targets

            frame = outcomes_for_targets(close, horizon, [target])[target]
            labels[horizon, target] = np.fromiter((study.LABEL_CODES[value] for value in frame["label"]), dtype=np.int8, count=len(frame))
            main[horizon, target] = frame["main_eligible"].to_numpy(dtype=bool)
            full[horizon] = frame["calendar_full"].to_numpy(dtype=bool)
    stock = study.StockDaily(
        code="2330",
        split="development",
        eligible=eligible,
        jump=study._jump_flags(reasons),
        c52w=np.zeros(n, dtype=bool),
        atoms={},
        ret120=np.full(n, np.nan),
        labels=labels,
        main_eligible=main,
        calendar_full=full,
    )
    return stock, reasons, close


@pytest.mark.parametrize("lookback", [0, 250])
def test_daily_counts_equal_pr17_projected_event_summaries(lookback: int) -> None:
    stock, reasons, close = _synthetic()
    members = np.random.default_rng(9).random(len(close)) > 0.5
    year_index = pd.Series(reasons.index).dt.year.to_numpy() - study.FIRST_YEAR
    ours = study.group_counts(stock, members, lookback=lookback, year_index=year_index, n_years=int(year_index.max()) + 1)

    dates = pd.Series(reasons.index).dt.strftime("%Y-%m-%d").to_numpy(dtype=object)
    days = np.flatnonzero(members & stock.eligible)
    events = pd.DataFrame([
        {
            "security_id": "TW:2330",
            "event_id": EventIdentity("TW:2330", dates[t], "C-x", "C-x", "def", "input").event_id,
            "t0": dates[t],
            "calendar_index": int(t),
            "pattern_id": "C-x",
            "subtype_id": "C-x",
            "definition_id": "def",
            "input_id": "input",
            "window_start": max(0, int(t) - lookback),
            "base_eligible": True,
            "eligibility_reason": None,
        }
        for t in days
    ])
    for horizon in (126, 252):
        base = outcomes_for_closes(close, horizon)
        base.insert(0, "security_id", "TW:2330")
        base.insert(1, "t0", dates)
        base.insert(2, "calendar_index", np.arange(len(dates)))
        base.insert(3, "horizon", horizon)
        projected = project_outcomes(events, base, reasons, base_label_version_id="v", base_label_manifest_sha256="0" * 64)
        projected["event_eligibility_excluded"] = False
        reference = summarize_events(projected)
        mine = ours[study.LABELS.index((horizon, 2.0))].sum(axis=0)
        for position, column in enumerate(study.METRICS):
            expected = len(days) if column == "event_n" else reference["full_calendar_unknown_n" if column == "full_unknown_n" else column]
            assert int(mine[position]) == expected, (horizon, column)


def test_cooldown_keeps_the_21st_session_and_ignores_ineligible_days() -> None:
    members = np.zeros(80, dtype=bool)
    members[[3, 10, 24, 25, 46, 60]] = True
    eligible = np.ones(80, dtype=bool)
    eligible[3] = False
    assert np.flatnonzero(study.cooled(members, eligible)).tolist() == [10, 46]


def test_merge_episodes_equals_pr17_at_horizon_126() -> None:
    from research_core.pattern_scan_events_v1 import merge_hit_episodes

    rng = np.random.default_rng(5)
    closes = 10 * np.exp(np.cumsum(rng.normal(0.003, 0.03, 700)))
    closes[[150, 410]] = np.nan
    starts = [10, 25, 40, 70, 140, 150, 300, 320, 560, 600]
    ours = study.merge_episodes(starts, closes, 126)
    pr17 = merge_hit_episodes(starts, [None if not np.isfinite(value) else float(value) for value in closes])
    assert [(e.start_indices, e.anchor_index, e.peak_index, e.status, e.reason) for e in ours] == [
        (e.start_indices, e.anchor_index, e.peak_index, e.status, e.reason) for e in pr17
    ]


def test_observation_runs_to_the_peak_and_keeps_unknowns_honest() -> None:
    closes = np.linspace(10, 60, 400)
    episode = study.LongEpisode((100,), 100, 300, "known")
    states = np.zeros(400, dtype=np.int8)
    states[250] = 1
    matched = study.observe_to_peak(episode, closes, states)
    assert matched["coverage_status"] == "matched" and matched["observed_offset"] == 150, "a match after anchor+40 still counts"
    assert matched["entry_return"] == pytest.approx(closes[250] / closes[100] - 1)
    states[250] = 0
    states[350] = 1
    assert study.observe_to_peak(episode, closes, states)["coverage_status"] == "unmatched", "after the peak does not count"
    states[90] = -1
    assert study.observe_to_peak(episode, closes, states)["coverage_status"] == "unknown"


def test_random_daily_draws_are_seeded_per_stock_year_and_record_shortfall() -> None:
    years = np.repeat([2015, 2016], 50)
    eligible = np.ones(100, dtype=bool)
    eligible[50:97] = False
    quota = np.zeros(100, dtype=bool)
    quota[[1, 2, 3, 60, 61, 62, 63, 64]] = True
    first, records = study.random_daily_draws(eligible, quota, years, group_id="A1", code="2330")
    second, _ = study.random_daily_draws(eligible, quota, years, group_id="A1", code="2330")
    assert np.array_equal(first, second) and first[:50].sum() == 3 and first[50:].sum() == 3
    assert [(r["year"], r["quota_n"], r["drawn_n"], r["shortfall_n"]) for r in records] == [(2015, 3, 3, 0), (2016, 5, 3, 2)]

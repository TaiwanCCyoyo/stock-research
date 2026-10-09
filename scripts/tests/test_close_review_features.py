"""Hand-calculable rolling features; all inputs are synthetic."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

LOCATION = Path(__file__).resolve().parents[2] / "tasks" / "20261005-relative-strength-holding" / "features.py"
SPEC = importlib.util.spec_from_file_location("close_review_features_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
features_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = features_module
SPEC.loader.exec_module(features_module)
build_policy_panel = features_module.build_policy_panel
FeatureError = features_module.FeatureError
TZ = timezone(timedelta(hours=8))


def inputs(size: int = 65, codes: tuple[str, ...] = ("A",)) -> tuple[pd.DataFrame, pd.DataFrame, tuple[date, ...], dict[date, frozenset[str]]]:
    calendar = tuple(date(2026, 1, 1) + timedelta(days=index) for index in range(size))
    rows = []
    for code in codes:
        for index, day in enumerate(calendar):
            close = float(100 + index)
            rows.append({
                "Market": "TWSE",
                "Code": code,
                "Date": pd.Timestamp(day),
                "Open": close,
                "High": close + 1,
                "Low": close - 1,
                "Close": close,
                "Volume": 200_000.0,
                "available_at": datetime.combine(day, datetime.min.time(), TZ) + timedelta(hours=18),
                "source_id": f"synthetic-raw-{code}",
            })
    raw = pd.DataFrame(rows)
    signal = cast(pd.DataFrame, raw[["Code", "Date", "Open", "High", "Low", "Close"]]).copy()
    return raw, signal, calendar, {day: frozenset(codes) for day in calendar}


def build(raw: pd.DataFrame, signal: pd.DataFrame, calendar: tuple[date, ...], universe: dict[date, frozenset[str]], **changes: Any) -> pd.DataFrame:
    return build_policy_panel(raw, signal, calendar=calendar, universe=universe, source_id="synthetic-panel-binding", **changes)


def row(panel: pd.DataFrame, code: str, day: date) -> pd.Series:
    return panel.loc[panel.Code.eq(code) & panel.Date.eq(pd.Timestamp(day))].iloc[0]


def test_sixty_observation_admission_but_ret60_requires_sixty_one() -> None:
    raw, signal, calendar, universe = inputs()
    original_raw, original_signal = raw.copy(deep=True), signal.copy(deep=True)
    result = build(raw.sample(frac=1, random_state=1), signal.sample(frac=1, random_state=2), calendar, universe)
    assert result.Date.tolist() == list(pd.DatetimeIndex(calendar))
    assert pd.isna(row(result, "A", calendar[18]).ma20)
    assert row(result, "A", calendar[19]).ma20 == pytest.approx(109.5)
    at60 = row(result, "A", calendar[59])
    assert at60.consecutive_usable == 60 and at60.rank_eligible
    assert at60.ma60 == pytest.approx(129.5)
    assert pd.isna(at60.ret60) and pd.isna(at60.rs60)
    assert not at60.eligible and at60.eligibility_reason == "ret60_requires_61_closes"
    at61 = row(result, "A", calendar[60])
    assert at61.ret60 == pytest.approx(0.6) and at61.rs60 == 1.0
    assert at61.ma20 == pytest.approx(150.5) and at61.ma60 == pytest.approx(130.5)
    assert at61.liquidity_twd == pytest.approx(150.5 * 200_000)
    assert at61.eligible
    assert at61.source_id == "synthetic-raw-A" and at61.panel_source_id == "synthetic-panel-binding"
    assert at61.available_at == raw.iloc[60].available_at
    pd.testing.assert_frame_equal(raw, original_raw)
    pd.testing.assert_frame_equal(signal, original_signal)


def test_average_ties_and_low_liquidity_member_ranks_before_gate() -> None:
    raw, signal, calendar, universe = inputs(61, ("A", "B", "C"))
    mask = signal.Code.eq("C")
    signal.loc[mask, ["Open", "High", "Low", "Close"]] *= 2
    # C has the same 60-session fractional return despite a different price.
    raw.loc[raw.Code.eq("C"), "Volume"] = 0.0
    result = build(raw, signal, calendar, universe)
    last = result.loc[result.Date.eq(pd.Timestamp(calendar[-1]))]
    assert last.rs60.tolist() == pytest.approx([2 / 3] * 3)
    assert last.eligible.tolist() == [True, True, False]
    assert row(result, "C", calendar[-1]).eligibility_reason == "liquidity_below_threshold"
    # Make the excluded-by-liquidity C strongest; it must still depress A/B ranks.
    signal.loc[mask & signal.Date.eq(pd.Timestamp(calendar[-1])), ["Open", "High", "Low", "Close"]] *= 2
    result = build(raw, signal, calendar, universe)
    assert row(result, "A", calendar[-1]).rs60 == pytest.approx(0.5)
    assert row(result, "B", calendar[-1]).rs60 == pytest.approx(0.5)
    assert row(result, "C", calendar[-1]).rs60 == 1.0


def test_missing_calendar_row_and_missing_ohlc_reset_all_price_histories() -> None:
    raw, signal, calendar, universe = inputs(125)
    absent = pd.Timestamp(calendar[61])
    raw = raw.loc[~raw.Date.eq(absent)].copy()
    signal = signal.loc[~signal.Date.eq(absent)].copy()
    result = build(raw, signal, calendar, universe)
    assert len(result) == 124 and not result.Date.eq(absent).any()
    after = row(result, "A", calendar[62])
    assert after.consecutive_usable == 1
    assert pd.isna(after.ma20) and pd.isna(after.ma60) and pd.isna(after.ret60)
    assert row(result, "A", calendar[121]).rank_eligible
    assert pd.isna(row(result, "A", calendar[121]).ret60)
    assert row(result, "A", calendar[122]).ret60 == pytest.approx(222 / 162 - 1)
    raw.loc[raw.Date.eq(pd.Timestamp(calendar[100])), "Open"] = np.nan
    result = build(raw, signal, calendar, universe)
    missing = row(result, "A", calendar[100])
    assert missing.consecutive_usable == 0 and missing.eligibility_reason == "missing_ohlc"
    assert pd.notna(missing.signal_close)  # source signal preserved; history unusable
    assert row(result, "A", calendar[101]).consecutive_usable == 1
    assert pd.isna(row(result, "A", calendar[101]).ma20)


def test_raw_and_signal_missing_values_both_reset_and_never_fill() -> None:
    raw, signal, calendar, universe = inputs(62)
    signal.loc[60, "Close"] = np.nan
    raw.loc[61, "Low"] = np.nan
    result = build(raw, signal, calendar, universe)
    assert pd.isna(row(result, "A", calendar[60]).signal_close)
    assert row(result, "A", calendar[60]).consecutive_usable == 0
    assert row(result, "A", calendar[61]).consecutive_usable == 0
    assert not row(result, "A", calendar[61]).eligible
    assert pd.isna(row(result, "A", calendar[61]).ma20)


def test_current_nonmember_excluded_but_price_history_and_exit_averages_survive() -> None:
    raw, signal, calendar, universe = inputs(63, ("A", "B"))
    universe[calendar[60]] = frozenset({"B"})
    universe[calendar[61]] = frozenset()
    result = build(raw, signal, calendar, universe)
    nonmember = row(result, "A", calendar[60])
    assert not nonmember.rank_eligible and pd.isna(nonmember.rs60)
    assert nonmember.eligibility_reason == "not_current_ordinary_member"
    assert nonmember.ma60 == pytest.approx(130.5) and nonmember.ret60 == pytest.approx(0.6)
    assert row(result, "B", calendar[60]).rs60 == 1.0
    assert row(result, "A", calendar[62]).consecutive_usable == 63
    assert row(result, "A", calendar[62]).rank_eligible
    all_nonmember: dict[date, frozenset[str]] = {day: frozenset() for day in calendar}
    assert build(raw, signal, calendar, all_nonmember).rs60.isna().all()


def test_liquidity_uses_raw_dollars_shares_and_twenty_known_sessions() -> None:
    raw, signal, calendar, universe = inputs(81)
    raw[["Open", "High", "Low", "Close"]] = [100.0, 101.0, 99.0, 100.0]
    signal[["Open", "High", "Low", "Close"]] = [10.0, 11.0, 9.0, 10.0]
    result = build(raw, signal, calendar, universe)
    assert row(result, "A", calendar[60]).liquidity_twd == 20_000_000
    assert row(result, "A", calendar[60]).eligible  # inclusive boundary
    raw.loc[60, "Volume"] = np.nan
    result = build(raw, signal, calendar, universe)
    assert pd.isna(row(result, "A", calendar[60]).liquidity_twd)
    assert row(result, "A", calendar[60]).eligibility_reason == "missing_liquidity"
    assert pd.isna(row(result, "A", calendar[79]).liquidity_twd)
    assert row(result, "A", calendar[80]).liquidity_twd == 20_000_000
    assert row(result, "A", calendar[60]).ret60 == 0.0  # liquidity loss not price-history loss


def test_prefix_invariance_future_prices_and_future_membership_do_not_rewrite_past() -> None:
    raw, signal, calendar, universe = inputs(65, ("A", "B"))
    full = build(raw, signal, calendar, universe)
    prefix_calendar = calendar[:62]
    cut = pd.Timestamp(prefix_calendar[-1])
    prefix = build(raw.loc[raw.Date.le(cut)], signal.loc[signal.Date.le(cut)], prefix_calendar, {day: universe[day] for day in prefix_calendar})
    pd.testing.assert_frame_equal(full.loc[full.Date.le(cut)].reset_index(drop=True), prefix)
    signal.loc[signal.Date.gt(cut), ["Open", "High", "Low", "Close"]] *= 100
    raw.loc[raw.Date.gt(cut), "Volume"] = 0
    for day in calendar[62:]:
        universe[day] = frozenset()
    changed = build(raw, signal, calendar, universe)
    pd.testing.assert_frame_equal(full.loc[full.Date.le(cut)].reset_index(drop=True), changed.loc[changed.Date.le(cut)].reset_index(drop=True))


@pytest.mark.parametrize(
    "target,column,value,match",
    [
        ("raw", "Open", "bad", "numeric"),
        ("signal", "Close", np.inf, "finite"),
        ("raw", "High", -1.0, "positive"),
        ("signal", "Low", 0.0, "positive"),
        ("raw", "Volume", -1.0, "nonnegative"),
        ("raw", "Volume", np.inf, "finite"),
        ("raw", "Volume", "200000", "numeric"),
        ("raw", "Market", "UNKNOWN", "Market"),
        ("raw", "source_id", "", "source_id"),
        ("raw", "Code", None, "Code"),
        ("signal", "Date", "01/02/2026", "ISO"),
    ],
)
def test_malformed_observed_inputs_rejected(target: str, column: str, value: Any, match: str) -> None:
    raw, signal, calendar, universe = inputs(61)
    chosen = raw if target == "raw" else signal
    chosen[column] = value
    with pytest.raises(FeatureError, match=match):
        build(raw, signal, calendar, universe)


def test_inconsistent_partial_ohlc_duplicates_mismatched_keys_and_scope_rejected() -> None:
    raw, signal, calendar, universe = inputs(61)
    bad = raw.copy()
    bad.loc[0, ["Open", "High", "Low"]] = [np.nan, 90.0, 95.0]
    with pytest.raises(FeatureError, match="inconsistent"):
        build(bad, signal, calendar, universe)
    with pytest.raises(FeatureError, match="duplicate"):
        build(pd.concat([raw, raw.iloc[:1]], ignore_index=True), signal, calendar, universe)
    with pytest.raises(FeatureError, match="one-to-one"):
        build(raw, signal.iloc[1:], calendar, universe)
    with pytest.raises(FeatureError, match="outside"):
        build(raw, signal, calendar[:-1], {day: universe[day] for day in calendar[:-1]})
    with pytest.raises(FeatureError, match="shares"):
        build(raw, signal, calendar, universe, raw_volume_unit="lots")


@pytest.mark.parametrize("bad", ["2026-01-01T20:01:00+08:00", "2026-01-02T18:00:00+08:00", "2026-01-01T18:00:00+00:00", "2026-01-01T18:00:00"])
def test_future_wrongday_wrongoffset_or_naive_availability_rejected(bad: str) -> None:
    raw, signal, calendar, universe = inputs(61)
    raw["available_at"] = raw.available_at.astype(object)
    raw.loc[0, "available_at"] = datetime.fromisoformat(bad)
    with pytest.raises(FeatureError, match="available_at"):
        build(raw, signal, calendar, universe)


def test_calendar_universe_and_source_binding_are_explicit() -> None:
    raw, signal, calendar, universe = inputs(61)
    for bad in (tuple(reversed(calendar)), (calendar[0], *calendar), tuple(pd.Timestamp(day) for day in calendar)):
        with pytest.raises(FeatureError, match="calendar"):
            build(raw, signal, cast(tuple[date, ...], bad), universe)
    with pytest.raises(FeatureError, match="every calendar"):
        build(raw, signal, calendar, {day: codes for day, codes in universe.items() if day != calendar[-1]})
    with pytest.raises(FeatureError, match="frozensets"):
        build(raw, signal, calendar, cast(dict[date, frozenset[str]], {day: {"A"} for day in calendar}))
    with pytest.raises(FeatureError, match="source_id"):
        build_policy_panel(raw, signal, calendar=calendar, universe=universe, source_id=" ")


def test_empty_original_keys_and_all_missing_volume_preserve_unknowns() -> None:
    raw, signal, calendar, universe = inputs(61)
    empty = build(raw.iloc[:0], signal.iloc[:0], calendar, universe)
    assert empty.empty and "eligible" in empty and "available_at" in empty
    raw["Volume"] = np.nan
    result = build(raw, signal, calendar, universe)
    assert result.liquidity_twd.isna().all()
    assert row(result, "A", calendar[-1]).rs60 == 1.0
    assert row(result, "A", calendar[-1]).eligibility_reason == "missing_liquidity"

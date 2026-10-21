from __future__ import annotations

import json
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from research_core.patterns.r1 import scan as scan_r1
from research_core.patterns.r2 import scan as scan_r2
from research_core.patterns.r3 import scan as scan_r3
from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, DetectorScan


def _frame(rows: int = 100) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": 111.0,
            "High": 120.0,
            "Low": 100.0,
            "Close": 110.0,
            "Volume": 100.0,
            "ATR14": 2.0,
            "RSI14": 50.0,
            "SMA20": 120.0,
            "F22": 0.0,
            "F23": 0.0,
            "F24": 0.0,
            "F25": 0.0,
        },
        index=pd.bdate_range("2020-01-01", periods=rows),
    )


def _bar(frame: pd.DataFrame, day: int, opening: float, high: float, low: float, close: float) -> None:
    frame.loc[frame.index[day], ["Open", "High", "Low", "Close"]] = [opening, high, low, close]


def _spring(offset: int = 0) -> pd.DataFrame:
    frame = _frame(100 + offset)
    _bar(frame, 60 + offset, 99, 101, 97, 99)
    _bar(frame, 61 + offset, 100, 103, 100, 101)
    _bar(frame, 64 + offset, 104, 105, 102, 103)
    _bar(frame, 65 + offset, 103, 106, 102, 104)
    return frame


def _candle() -> pd.DataFrame:
    frame = _frame()
    _bar(frame, 39, 101, 102, 99, 100)
    _bar(frame, 59, 91, 92, 89, 90)
    _bar(frame, 60, 89, 93, 88, 91)
    _bar(frame, 61, 93, 95, 50, 94)
    frame.loc[frame.index[60], ["F22", "F23", "F24", "F25"]] = 1
    return frame


def _divergence() -> pd.DataFrame:
    frame = _frame()
    _bar(frame, 10, 93, 95, 90, 92)
    _bar(frame, 30, 88, 90, 85, 87)
    frame.loc[frame.index[10], "RSI14"] = 25
    frame.loc[frame.index[30], "RSI14"] = 35
    frame.loc[frame.index[34], "RSI14"] = 51
    return frame


def _event(result: DetectorScan, subtype: str, day: int) -> DetectorEvent:
    return next(event for event in result.events if event.subtype_id == subtype and event.t0 == day)


def test_spring_recovery_and_retest_use_actual_confirmation_and_fixed_levels() -> None:
    result = scan_r1(Bars.from_frame(_spring()))
    first = _event(result, "R1a", 61)
    second = _event(result, "R1b", 65)
    assert first.window_start == 0
    assert first.pivot == first.support == second.support == 100
    assert first.lower == second.lower == 97
    assert dict(first.details)["break_index"] == 60
    assert dict(second.details)["retest_index"] == 64
    assert result.states[64, 1] != 1
    assert result.states[65, 1] == 1


@pytest.mark.parametrize("change", ["range", "depth", "recovery_equal", "touch_distance"])
def test_spring_near_misses(change: str) -> None:
    frame = _spring()
    if change == "range":
        frame.loc[frame.index[0], "High"] = 135.001
    elif change == "depth":
        frame.loc[frame.index[60], "Low"] = 96.999
    elif change == "recovery_equal":
        frame.loc[frame.index[61], "Close"] = 100
    else:
        frame.loc[frame.index[:60], "Low"] = 104
        frame.loc[frame.index[0:10], "Low"] = 100
    assert scan_r1(Bars.from_frame(frame)).states[61, 0] == 0


def test_spring_inclusive_range_depth_and_touches() -> None:
    frame = _spring()
    frame.loc[frame.index[0], "High"] = 135
    frame.loc[frame.index[:60], "Low"] = 104
    frame.loc[frame.index[[0, 10]], "Low"] = 100
    assert scan_r1(Bars.from_frame(frame)).states[61, 0] == 1


@pytest.mark.parametrize("delay,expected", [(1, 1), (5, 1), (6, 0)])
def test_spring_first_recovery_deadline(delay: int, expected: int) -> None:
    frame = _spring()
    for day in range(61, 67):
        _bar(frame, day, 100, 101, 98, 99)
    _bar(frame, 60 + delay, 100, 103, 98, 102)
    assert scan_r1(Bars.from_frame(frame)).states[60 + delay, 0] == expected


@pytest.mark.parametrize("delay,expected", [(1, 1), (5, 1), (6, 0)])
def test_retest_bullish_confirmation_deadline(delay: int, expected: int) -> None:
    # Fully warm all alternative R1a ancestors before asserting a known false.
    frame = _spring(30)
    for day in range(95, 101):
        _bar(frame, day, 105, 106, 102, 104)
    _bar(frame, 94 + delay, 103, 106, 102, 104)
    assert scan_r1(Bars.from_frame(frame)).states[94 + delay, 1] == expected


@pytest.mark.parametrize("retest", [64, 76])
def test_retest_three_and_fifteen_day_boundaries(retest: int) -> None:
    frame = _spring()
    for day in range(64, 78):
        _bar(frame, day, 111, 120, 100, 110)
    _bar(frame, retest, 104, 105, 102, 103)
    _bar(frame, retest + 1, 103, 106, 102, 104)
    assert scan_r1(Bars.from_frame(frame)).states[retest + 1, 1] == 1


def test_retest_cannot_close_below_original_lower_even_on_confirmation() -> None:
    frame = _spring(30)
    _bar(frame, 95, 95, 99, 94, 96)
    assert scan_r1(Bars.from_frame(frame)).states[95, 1] == 0


@pytest.mark.parametrize("subtype,col", [("R2a", 0), ("R2b", 1), ("R2c", 2), ("R2d", 3)])
def test_canonical_flags_are_preserved_and_e_keeps_original_levels(subtype: str, col: int) -> None:
    result = scan_r2(Bars.from_frame(_candle()))
    event = _event(result, subtype, 60)
    confirmed = _event(result, "R2e", 61)
    assert result.states[60, col] == 1
    assert result.states[60, 4] == 0
    assert event.support == event.lower == confirmed.support == confirmed.lower == 88
    assert event.pivot == confirmed.pivot == 93
    assert dict(confirmed.details)["source_t0"] == 60
    sources = json.loads(str(dict(confirmed.details)["matching_sources_json"]))
    assert [source["subtype_id"] for source in sources] == ["R2a", "R2b", "R2c", "R2d"]


@pytest.mark.parametrize("change", ["ret", "ma", "low", "flag"])
def test_candle_gates_near_misses(change: str) -> None:
    frame = _candle()
    if change == "ret":
        frame.loc[frame.index[59], "Close"] = 90.001
    elif change == "ma":
        frame.loc[frame.index[59], "SMA20"] = 90
    elif change == "low":
        frame.loc[frame.index[30], "Low"] = 50
    else:
        frame.loc[frame.index[60], ["F22", "F23", "F24", "F25"]] = 0
    assert not np.any(scan_r2(Bars.from_frame(frame)).states[60, :4] == 1)


def test_candle_confirmation_strict_high_and_next_day_only() -> None:
    frame = _candle()
    frame.loc[frame.index[61], "Close"] = 93
    assert scan_r2(Bars.from_frame(frame)).states[61, 4] == 0
    assert scan_r2(Bars.from_frame(frame)).states[62, 4] == 0


def test_hammer_is_one_bar_but_other_sources_include_previous_bar() -> None:
    frame = _candle()
    frame.loc[frame.index[59], "Low"] = 80
    frame.loc[frame.index[60], "Low"] = 82
    result = scan_r2(Bars.from_frame(frame))
    assert _event(result, "R2a", 60).lower == 80
    assert _event(result, "R2d", 60).lower == 82


def test_divergence_pivot_confirmation_and_delayed_swing() -> None:
    result = scan_r3(Bars.from_frame(_divergence()))
    first = _event(result, "R3a", 33)
    swing = _event(result, "R3b", 34)
    assert first.lower == swing.lower == 85
    assert first.pivot == swing.pivot == 87
    assert dict(first.details)["p2_index"] == 30
    assert dict(first.details)["p2_confirmed_index"] == 33
    assert result.states[30, 0] != 1
    assert result.states[33, 1] != 1


@pytest.mark.parametrize("change", ["equal_low", "equal_rsi", "rsi_above30", "equal_confirm_close"])
def test_divergence_near_misses(change: str) -> None:
    frame = _divergence()
    if change == "equal_low":
        frame.loc[frame.index[30], "Low"] = 90
        frame.loc[frame.index[30], ["Open", "Close"]] = 92
        frame.loc[frame.index[30], "High"] = 95
    elif change == "equal_rsi":
        frame.loc[frame.index[30], "RSI14"] = 25
    elif change == "rsi_above30":
        frame.loc[frame.index[10], "RSI14"] = 30.001
    else:
        _bar(frame, 33, 88, 90, 86, 87)
    assert scan_r3(Bars.from_frame(frame)).states[33, 0] == 0


def test_rsi30_is_inclusive_and_b_does_not_inherit_a_close_gate() -> None:
    frame = _divergence()
    frame.loc[frame.index[10], "RSI14"] = 30
    assert scan_r3(Bars.from_frame(frame)).states[33, 0] == 1
    _bar(frame, 33, 88, 90, 86, 87)
    result = scan_r3(Bars.from_frame(frame))
    assert result.states[33, 0] == 0
    assert result.states[34, 1] == 1


def test_low_tie_uses_earliest_and_nearest_legal_first_pivot() -> None:
    frame = _divergence()
    _bar(frame, 20, 92, 94, 89, 91)
    frame.loc[frame.index[20], "RSI14"] = 28
    assert dict(_event(scan_r3(Bars.from_frame(frame)), "R3a", 33).details)["p1_index"] == 20
    _bar(frame, 29, 88, 90, 85, 87)
    assert scan_r3(Bars.from_frame(frame)).states[33, 0] == 0


def test_swing_threshold_excludes_both_low_endpoints() -> None:
    frame = _divergence()
    frame.loc[frame.index[11:30], "RSI14"] = 20
    frame.loc[frame.index[34], "RSI14"] = 21
    result = scan_r3(Bars.from_frame(frame))
    details = dict(_event(result, "R3b", 34).details)
    assert details["rsi_threshold"] == 20
    assert details["threshold_window_start"] == 11
    assert details["threshold_window_end"] == 29


@pytest.mark.parametrize("delay,expected", [(1, 1), (20, 1), (21, 0)])
def test_failure_swing_deadline_and_strict_threshold(delay: int, expected: int) -> None:
    frame = _divergence()
    frame.loc[frame.index[34:55], "RSI14"] = 50
    frame.loc[frame.index[33 + delay], "RSI14"] = 51
    assert scan_r3(Bars.from_frame(frame)).states[33 + delay, 1] == expected


@pytest.mark.parametrize("gap,expected", [(9, 0), (10, 1), (60, 1), (61, 0)])
def test_divergence_pair_distance_boundaries(gap: int, expected: int) -> None:
    frame = _frame()
    _bar(frame, 10, 93, 95, 90, 92)
    _bar(frame, 10 + gap, 88, 90, 85, 87)
    frame.loc[frame.index[10], "RSI14"] = 25
    frame.loc[frame.index[10 + gap], "RSI14"] = 35
    assert scan_r3(Bars.from_frame(frame)).states[13 + gap, 0] == expected


@pytest.mark.parametrize(
    "scan,fixture,col,missing_day,column,day",
    [
        (scan_r1, _spring, 0, 60, "ATR14", 61),
        (scan_r1, _spring, 1, 62, "Close", 65),
        (scan_r2, _candle, 0, 60, "F22", 60),
        (scan_r2, _candle, 0, 30, "Close", 60),
        (scan_r2, _candle, 4, 61, "Close", 61),
        (scan_r3, _divergence, 0, 25, "RSI14", 33),
        (scan_r3, _divergence, 1, 34, "RSI14", 34),
    ],
)
def test_missing_required_windows_are_unknown(
    scan: Callable[[Bars], DetectorScan], fixture: Callable[[], pd.DataFrame], col: int, missing_day: int, column: str, day: int
) -> None:
    frame = fixture()
    frame.loc[frame.index[missing_day], column] = np.nan
    result = scan(Bars.from_frame(frame))
    assert result.states[day, col] == -1
    assert any(index == day and subtype == result.subtype_ids[col] for subtype, index, _ in result.unknown_reasons)


@pytest.mark.parametrize("scan,fixture", [(scan_r1, _spring), (scan_r2, _candle), (scan_r3, _divergence)])
def test_warmup_is_explicit_and_every_subtype_is_suffix_invariant(scan: Callable[[Bars], DetectorScan], fixture: Callable[[], pd.DataFrame]) -> None:
    frame = fixture()
    full = scan(Bars.from_frame(frame))
    if scan is scan_r2:
        assert np.all(full.states[0, :4] == 0)  # Known canonical false needs no unused history.
        assert full.states[0, 4] == -1
    else:
        assert np.all(full.states[0] == -1)
    for cut in range(len(frame) + 1):
        prefix = scan(Bars.from_frame(frame.iloc[:cut]))
        np.testing.assert_array_equal(prefix.states, full.states[:cut])
        assert prefix.events == tuple(event for event in full.events if event.t0 < cut)


def test_positive_confirmation_absorbs_unknown_candle_alternative() -> None:
    frame = _candle()
    frame.loc[frame.index[60], "F22"] = np.nan
    result = scan_r2(Bars.from_frame(frame))
    assert result.states[60, 0] == -1
    assert result.states[61, 4] == 1
    assert dict(_event(result, "R2e", 61).details)["source_subtype"] == "R2b"


def test_false_canonical_candles_do_not_need_unused_history_but_true_and_unknown_do() -> None:
    frame = _frame(5)
    frame.loc[frame.index[0], "F23"] = 1
    frame.loc[frame.index[0], "F24"] = np.nan
    result = scan_r2(Bars.from_frame(frame))
    assert result.states[0, :4].tolist() == [0, -1, -1, 0]
    assert result.states[1, 4] == -1
    assert result.states[2, 4] == 0


def test_known_false_decline_absorbs_unknown_flag() -> None:
    frame = _candle()
    frame.loc[frame.index[60], "F22"] = np.nan
    frame.loc[frame.index[59], "Close"] = 91
    assert scan_r2(Bars.from_frame(frame)).states[60, 0] == 0


def test_no_original_candle_absorbs_missing_confirmation_bar() -> None:
    frame = _frame(5)
    frame.loc[frame.index[1], "Close"] = np.nan
    assert scan_r2(Bars.from_frame(frame)).states[1, 4] == 0

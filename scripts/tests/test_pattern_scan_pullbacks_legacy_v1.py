"""Synthetic exact-flag parity and causal confirmation tests."""

import json
from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from research_core.feature_atlas_features import compute_features
from research_core.feature_atlas_legacy import compute_legacy_features
from research_core.patterns import l1, l2, l3, p1
from research_core.patterns.scan_contract_v1 import Bars, DetectorScan


def frame(length: int = 110) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 10.0, "Turnover": 1000.0}, index=pd.date_range("2020-01-01", periods=length)
    )


def set_bar(data: pd.DataFrame, index: int, close: float, *, low: float | None = None, high: float | None = None, volume: float = 10) -> None:
    data.loc[data.index[index], ["Open", "High", "Low", "Close", "Volume"]] = [
        close,
        high if high is not None else close + 1,
        low if low is not None else close - 1,
        close,
        volume,
    ]


def supplied(data: pd.DataFrame) -> Bars:
    result = data.copy()
    features = compute_features(data)
    for name in ("F10", "F32"):
        result[name] = features[name]
    result["F33"] = compute_legacy_features(data)["F33"]
    result["SMA60"] = data.Close.rolling(60).mean()
    return Bars.from_frame(result)


@pytest.mark.parametrize("module, flag", [(l1, "F10"), (l2, "F32"), (l3, "F33")])
def test_original_public_flag_parity(module: object, flag: str) -> None:
    data = frame(160)
    rng = np.random.default_rng(25)
    for i, close in enumerate(100 + rng.normal(size=160).cumsum()):
        set_bar(data, i, float(close))
    data.loc[data.index[80], "Open"] = np.nan
    bars = supplied(data)
    scanner: Callable[[Bars], DetectorScan] = getattr(module, "scan")
    scan = scanner(bars)
    expected = bars.values(flag)
    np.testing.assert_array_equal(scan.states[:, 0], np.where(np.isnan(expected), -1, expected).astype(np.int8))


def test_l1_strict_breakout_and_metadata() -> None:
    data = frame()
    set_bar(data, 60, 101)
    set_bar(data, 61, 103)
    scan = l1.scan(supplied(data))
    assert scan.states[60, 0] == 0
    event = next(e for e in scan.events if e.t0 == 61)
    assert (event.pivot, event.support, event.lower, event.window_start) == (102, 102, 99, 1)


@pytest.mark.parametrize("close, expected", [(103, 1), (105, 0)])
def test_l2_five_day_negative_return_strict(close: float, expected: int) -> None:
    data = frame()
    set_bar(data, 60, 105)
    set_bar(data, 65, close, low=98)
    scan = l2.scan(supplied(data))
    assert scan.states[65, 0] == expected
    if expected:
        event = next(e for e in scan.events if e.t0 == 65)
        assert event.support == pytest.approx(data.Close.iloc[6:66].mean())
        assert event.lower == 98


@pytest.mark.parametrize("reclaim, expected", [(25, 1), (26, 0)])
def test_l3_deadline_same_day_and_strict_reclaim(reclaim: int, expected: int) -> None:
    data = frame(50)
    data.loc[:, "Low"] = 90
    set_bar(data, 20, 100, low=89)
    for i in range(21, reclaim):
        set_bar(data, i, 90, low=90)
    scan = l3.scan(supplied(data))
    assert scan.states[20, 0] == 0
    assert scan.states[reclaim, 0] == expected
    if expected:
        event = scan.events[0]
        assert event.support == 90 and event.lower == 89
        assert dict(event.details)["break_index"] == 20


def test_l3_new_strict_low_resets_and_gap_clears() -> None:
    data = frame(55)
    data.loc[:, "Low"] = 90
    set_bar(data, 20, 90, low=89)
    set_bar(data, 21, 89, low=89)
    set_bar(data, 22, 89, low=88)
    set_bar(data, 23, 89.5, low=89)
    scan = l3.scan(supplied(data))
    event = scan.events[0]
    assert event.t0 == 23 and event.support == 89 and event.lower == 88
    data.loc[data.index[23], "Open"] = np.nan
    scan = l3.scan(supplied(data))
    assert scan.states[23:44, 0].tolist() == [-1] * 21


def pullback() -> pd.DataFrame:
    data = frame()
    set_bar(data, 85, 105, volume=15)
    set_bar(data, 86, 105)
    set_bar(data, 87, 104)
    set_bar(data, 88, 101, high=102, low=99)
    set_bar(data, 89, 103, low=100)
    return data


def test_p1_confirmation_is_past_only_and_volume_equality_inclusive() -> None:
    data = pullback()
    scan = p1.scan(Bars.from_frame(data))
    assert scan.states[85:89, 0].tolist() == [0] * 4
    event = scan.events[0]
    assert event.t0 == 89 and event.support == 101 and event.lower == 99
    assert dict(event.details)["paired_control_index"] == 85
    assert p1.scan(Bars.from_frame(data.iloc[:89])).events == ()


def test_p1_same_confirmation_keeps_earliest_and_audits_alternate() -> None:
    data = pullback()
    set_bar(data, 86, 107, volume=20)
    set_bar(data, 87, 105)
    set_bar(data, 88, 103, high=104)
    set_bar(data, 89, 103, high=104)
    set_bar(data, 90, 105)
    event = next(e for e in p1.scan(Bars.from_frame(data)).events if e.t0 == 90)
    details = dict(event.details)
    assert details["breakout_index"] == 85
    alternates = json.loads(str(details["alternate_ancestors"]))
    assert alternates == [{"breakout_index": 86, "retest_index": 89, "resistance": 106.0}]


def test_p1_complete_event_survives_another_unknown_ancestor() -> None:
    data = pullback()
    data.loc[data.index[10], "Open"] = np.nan
    event = p1.scan(Bars.from_frame(data)).events[0]
    assert event.t0 == 89


@pytest.mark.parametrize("change", ["low_volume", "failed_support", "late_retest", "late_confirm", "gap"])
def test_p1_near_misses(change: str) -> None:
    data = pullback()
    if change == "low_volume":
        data.loc[data.index[85], "Volume"] = 14.99
    elif change == "failed_support":
        set_bar(data, 87, 97)
    elif change == "gap":
        data.loc[data.index[87], "Open"] = np.nan
    elif change == "late_retest":
        for i in range(88, 106):
            set_bar(data, i, 105)
        set_bar(data, 106, 101)
        set_bar(data, 107, 103)
    else:
        for i in range(89, 94):
            set_bar(data, i, 101)
        set_bar(data, 94, 103)
    scan = p1.scan(Bars.from_frame(data))
    assert not scan.events
    if change == "gap":
        assert scan.states[89, 0] == -1


@pytest.mark.parametrize("scanner", [p1.scan, l1.scan, l2.scan, l3.scan])
def test_future_suffix_preserves_all_prior_states_and_events(scanner: Callable[[Bars], DetectorScan]) -> None:
    data = pullback()
    full = scanner(supplied(data))
    prefix = scanner(supplied(data.iloc[:90]))
    np.testing.assert_array_equal(prefix.states, full.states[:90])
    assert prefix.events == tuple(e for e in full.events if e.t0 < 90)
    assert prefix.unknown_reasons == tuple(reason for reason in full.unknown_reasons if reason[1] < 90)


@pytest.mark.parametrize("scanner, flag", [(l1.scan, "F10"), (l2.scan, "F32"), (l3.scan, "F33")])
def test_adapter_rejects_changed_canonical_flag(scanner: Callable[[Bars], DetectorScan], flag: str) -> None:
    data = frame()
    bars = supplied(data)
    corrupted = data.copy()
    for name, values in bars.columns.items():
        corrupted[name] = values
    corrupted.loc[corrupted.index[70], flag] = 1
    with pytest.raises(ValueError, match="parity mismatch"):
        scanner(Bars.from_frame(corrupted))

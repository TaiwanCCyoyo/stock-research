"""Invented-price contracts and exact trusted-source H1 adapter parity."""

from dataclasses import FrozenInstanceError

import numpy as np
import pandas as pd
import pytest

from research_core.patterns.h1 import scan_with_sources, source_detector
from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, finish_scan, prior_mean


def signal() -> pd.DataFrame:
    t = np.arange(360, dtype=float)
    close = 100 + 0.1 * t + 5 * np.sin(2 * np.pi * t / 20)
    volume = np.full(len(t), 100.0)
    for day in range(20, len(t)):
        if close[day] > close[day - 20 : day].max():
            volume[day] = 300
    return pd.DataFrame(
        {"Open": close, "High": close + 0.3, "Low": close - 0.3, "Close": close, "RawClose": close, "Volume": volume, "ATR14": close * 0.01},
        index=pd.date_range("2010-01-04", periods=len(t)),
    )


def test_bars_own_readonly_values_and_preserve_missing_positions() -> None:
    frame = signal()
    frame.iloc[10, frame.columns.get_loc("Close")] = np.nan
    bars = Bars.from_frame(frame)
    assert not bars.complete(0, 20) and bars.complete(11, 20)
    assert not bars.complete(-1, 0)
    old = bars.values("Open")[0]
    frame.iloc[0, 0] = 1
    assert bars.values("Open")[0] == old
    with pytest.raises(ValueError):
        bars.values("Open")[0] = 1
    with pytest.raises(FrozenInstanceError):
        setattr(bars, "dates", ())


def test_prior_window_excludes_today_and_requires_all_values() -> None:
    values = np.array([1.0, 2.0, 30.0, np.nan, 5.0, 6.0])
    np.testing.assert_equal(prior_mean(values, 2), [np.nan, np.nan, 1.5, 16.0, np.nan, np.nan])


def test_true_and_unknown_observations_must_have_exact_records() -> None:
    with pytest.raises(ValueError, match="every true"):
        finish_scan("X", ("x",), np.ones((1, 1), dtype=np.int8), [], [])
    with pytest.raises(ValueError, match="every unknown"):
        finish_scan("X", ("x",), -np.ones((1, 1), dtype=np.int8), [], [])
    event = DetectorEvent("X", "x", 0, 0, 2.0, 1.0, 1.0)
    result = finish_scan("X", ("x",), np.ones((1, 1), dtype=np.int8), [event], [])
    assert result.events == (event,) and not result.states.flags.writeable


def test_h1_raw_event_source_and_pattern_metadata_parity() -> None:
    frame = signal()
    expected_input = frame.rename(columns={"Volume": "VolumeLots"}).copy()
    expected_input["asof_date"] = pd.DatetimeIndex(frame.index).strftime("%Y-%m-%d")
    expected_input["atr14_pct"] = frame["ATR14"] / frame["Close"]
    expected = source_detector()(expected_input)
    result, original = scan_with_sources(Bars.from_frame(frame))
    assert expected and len(original) == len(expected)
    assert [row["t"] for row in original] == [row["t"] for row in expected]
    assert len(result.events) == sum(bool(row["pattern"]) for row in expected)
    for event in result.events:
        row = next(row for row in expected if row["t"] == event.t0)
        assert event.pivot == row["hz_top"]
        assert event.support == next(point["p"] for point in reversed(row["seq"]) if point["k"] == "L")
        assert event.lower == frame["Low"].iloc[row["restart"]]


def test_h1_prefix_causality_and_gap_segment_remapping() -> None:
    frame = signal()
    complete, _ = scan_with_sources(Bars.from_frame(frame))
    prefix, _ = scan_with_sources(Bars.from_frame(frame.iloc[:150]))
    np.testing.assert_equal(prefix.states, complete.states[:150])
    assert prefix.events == tuple(row for row in complete.events if row.t0 < 150)
    frame.iloc[180, frame.columns.get_loc("Close")] = np.nan
    result, sources = scan_with_sources(Bars.from_frame(frame))
    assert tuple(result.states[180]) == (-1, -1)
    assert all(row["restart"] >= 181 for row in sources if row["t"] >= 181)
    assert any(row.t0 > 200 and row.window_start == 181 for row in result.events)

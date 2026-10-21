from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd
import pytest

from research_core.patterns import b1, b2, b3, b4
from research_core.patterns.scan_contract_v1 import Bars, DetectorScan


def _frame(n: int, price: float = 90) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": float(price), "High": float(price + 1), "Low": float(price - 1), "Close": float(price), "Volume": 1000.0},
        index=pd.date_range("2020-01-01", periods=n),
    )


def _cup(handle: bool) -> pd.DataFrame:
    frame = _frame(401, 70)
    t = 400
    left = 365 if handle else 370
    frame.iloc[150:t, :4] = [90, 91, 89, 90]
    # A 70 close inside the rim's prior 120 sessions establishes the required
    # 30% rise. It is before the cup, so it cannot deepen the cup itself.
    frame.iloc[left - 100, :4] = [70, 71, 69, 70]
    frame.iloc[left, :4] = [100, 100, 99, 100]
    frame.iloc[left + 1 : t - 5 if handle else t, :4] = [85, 90, 80, 85]
    if handle:
        frame.iloc[t - 5 : t, :4] = [95, 96, 94, 95]
    frame.iloc[t, :4] = [101, 103, 100, 102]
    frame.iloc[t, 4] = 1400
    return frame


def _bollinger() -> pd.DataFrame:
    frame = _frame(161, 10)
    frame["BBUpper"] = 11.0
    frame["BBWidth"] = 2.0
    frame.iloc[-2, frame.columns.get_loc("BBWidth")] = 1.0
    frame.iloc[-1, :5] = [11, 13, 10, 12, 1500]
    return frame


def _platform() -> pd.DataFrame:
    frame = _frame(151, 100)
    frame.iloc[125:150, :4] = [125, 126, 110, 125]
    frame.iloc[142:150, :4] = [125, 126, 120, 125]
    frame.iloc[140:150, 4] = 500
    frame.iloc[150, :5] = [128, 131, 127, 130, 1500]
    return frame


def _gap() -> pd.DataFrame:
    frame = _frame(81, 10)
    frame["High"] = 10.0
    frame.iloc[-1, :5] = [10.2, 11, 10.1, 10.5, 2000]
    return frame


CASES: list[tuple[Callable[[], pd.DataFrame], Callable[[Bars], DetectorScan], str]] = [
    (lambda: _cup(True), b1.scan, "B1a"),
    (lambda: _cup(False), b1.scan, "B1b"),
    (_bollinger, b2.scan, "B2a"),
    (_bollinger, b2.scan, "B2b"),
    (_platform, b3.scan, "B3a"),
    (_platform, b3.scan, "B3b"),
    (_platform, b3.scan, "B3c"),
    (_gap, b4.scan, "B4"),
]


@pytest.mark.parametrize("factory,scanner,subtype", CASES)
def test_positive_missing_warmup_and_suffix(factory: Callable[[], pd.DataFrame], scanner: Callable[[Bars], DetectorScan], subtype: str) -> None:
    frame = factory()
    result = scanner(Bars.from_frame(frame))
    col = result.subtype_ids.index(subtype)
    assert result.states[-1, col] == 1
    event = next(row for row in result.events if row.subtype_id == subtype and row.t0 == len(frame) - 1)
    assert event.window_start <= event.t0 and dict(event.details)["confirmation_index"] == event.t0
    assert result.states[0, col] == -1
    missing = frame.copy()
    missing.iloc[-2, missing.columns.get_loc("Close")] = np.nan
    assert scanner(Bars.from_frame(missing)).states[-1, col] == -1
    suffix = frame.iloc[-1:].copy()
    suffix.index += pd.Timedelta(days=1)
    extended = scanner(Bars.from_frame(pd.concat([frame, suffix])))
    np.testing.assert_array_equal(extended.states[:-1], result.states)
    assert tuple(row for row in extended.events if row.t0 < len(frame)) == result.events


@pytest.mark.parametrize("factory,scanner,subtype", CASES)
def test_breakout_near_miss(factory: Callable[[], pd.DataFrame], scanner: Callable[[Bars], DetectorScan], subtype: str) -> None:
    frame = factory()
    if subtype == "B4":
        frame.iloc[-1, frame.columns.get_loc("Low")] = 10.0
    else:
        close = {"B1a": 96, "B1b": 100, "B2a": 11, "B2b": 11, "B3a": 126, "B3b": 126, "B3c": 126}[subtype]
        frame.iloc[-1, frame.columns.get_loc("Close")] = close
        frame.iloc[-1, frame.columns.get_loc("Low")] = close - 1
        frame.iloc[-1, frame.columns.get_loc("Open")] = close
    result = scanner(Bars.from_frame(frame))
    assert result.states[-1, result.subtype_ids.index(subtype)] == 0


def test_cup_no_handle_nearest_equal_rim_and_no_volume_gate() -> None:
    frame = _cup(False)
    frame.iloc[369, :4] = [100, 100, 99, 100]
    frame.iloc[-1, 4] = np.nan
    result = b1.scan(Bars.from_frame(frame))
    event = next(row for row in result.events if row.t0 == 400 and row.subtype_id == "B1b")
    assert dict(event.details)["left_index"] == 370
    assert dict(event.details)["cup_length"] == 30


def test_handle_high_equal_tie_uses_earliest_and_depth_threshold() -> None:
    frame = _cup(True)
    frame.iloc[398, frame.columns.get_loc("High")] = 96
    result = b1.scan(Bars.from_frame(frame))
    event = next(row for row in result.events if row.t0 == 400 and row.subtype_id == "B1a")
    assert dict(event.details)["handle_high_index"] == 395
    frame.iloc[398, frame.columns.get_loc("High")] = 97
    assert b1.scan(Bars.from_frame(frame)).states[-1, 0] == 0


def test_bollinger_bandwidth_and_volume_equalities_are_inclusive() -> None:
    frame = _bollinger()
    frame["BBWidth"] = 2.0
    result = b2.scan(Bars.from_frame(frame))
    assert tuple(result.states[-1]) == (1, 1)
    frame.iloc[-1, 4] = 1499
    assert tuple(b2.scan(Bars.from_frame(frame)).states[-1]) == (1, 0)


def test_platform_volume_subtype_is_independent_and_tightness_strict() -> None:
    frame = _platform()
    frame.iloc[140:150, 4] = 1000
    assert tuple(b3.scan(Bars.from_frame(frame)).states[-1]) == (1, 0, 1)
    # Exact widths: first third 126-116=10, last third 126-120=6.
    # Longer windows start on baseline close=100 and fail the 25% rise gate.
    frame.iloc[125:142, frame.columns.get_loc("Low")] = 116
    assert b3.scan(Bars.from_frame(frame)).states[-1, 2] == 0


def test_gap_open_and_volume_equalities_and_strict_low() -> None:
    frame = _gap()
    assert b4.scan(Bars.from_frame(frame)).states[-1, 0] == 1
    frame.iloc[-1, 4] = 1999
    assert b4.scan(Bars.from_frame(frame)).states[-1, 0] == 0

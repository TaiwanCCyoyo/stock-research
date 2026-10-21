from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_controls_v1 import ControlScan, base_no_pattern, scan_controls
from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent


def _frame(n: int = 300) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1000.0, "ATR14": 1.0, "RawClose": 100.0},
        index=pd.date_range("2020-01-01", periods=n),
    )


def _scan(frame: pd.DataFrame, *, excluded: int | None = None, sources: tuple[dict[str, object], ...] = ()) -> Mapping[str, ControlScan]:
    eligible = np.ones(len(frame), dtype=np.bool_)
    if excluded is not None:
        eligible[excluded] = False
    return scan_controls(Bars.from_frame(frame), base_eligible=eligible, h1_source_events=sources)


def test_52w_equalities_prior_only_and_cooldown() -> None:
    frame = _frame()
    frame.iloc[250:, frame.columns.get_loc("Volume")] = 1500.0
    result = _scan(frame)
    assert result["C-52w"].states[250] == 1
    assert result["C-52w"].states[249] == -1
    assert result["C-base"].cooled_indices[:3] == (0, 21, 42)
    frame.iloc[250, frame.columns.get_loc("Volume")] = 1499.0
    assert _scan(frame)["C-52w"].states[250] == 0


def test_nh_no_limit_up_exemption_and_false_source_exclusion() -> None:
    frame = _frame()
    frame.iloc[-1, :4] = [110, 112, 109, 111]
    assert _scan(frame)["C-nh"].states[-1] == 0
    frame.iloc[-1, frame.columns.get_loc("Volume")] = 1500
    assert _scan(frame)["C-nh"].states[-1] == 1
    assert _scan(frame, sources=({"t": 299, "pattern": False},))["C-nh"].states[-1] == 0


@pytest.mark.parametrize("column", ("Close", "ATR14", "RawClose", "Volume"))
def test_nh_good_segment_reset_and_unknown_eligibility_separation(column: str) -> None:
    frame = _frame()
    frame.iloc[279, frame.columns.get_loc(column)] = np.nan
    result = _scan(frame, excluded=280)["C-nh"]
    assert result.formula_states[280] == -1
    assert result.states[280] == 0 and 280 in result.eligibility_excluded
    assert result.states[299] == -1
    frame.iloc[279, frame.columns.get_loc(column)] = 100 if column != "Volume" else 1000
    assert _scan(frame)["C-nh"].states[299] == 0


def test_dip_equal_boundary_and_strict_previous_close() -> None:
    frame = _frame()
    frame.iloc[-2, :4] = [79, 80, 78, 79]
    frame.iloc[-1, :4] = [80, 81, 79, 80]
    assert _scan(frame)["C-dip"].states[-1] == 1
    frame.iloc[-1, frame.columns.get_loc("Close")] = 79
    assert _scan(frame)["C-dip"].states[-1] == 0


def test_trend_current_ma_and_strict_equalities() -> None:
    frame = _frame()
    assert _scan(frame)["C-trend"].states[-1] == 0
    frame.iloc[-1, :4] = [110, 112, 109, 111]
    assert _scan(frame)["C-trend"].states[-1] == 1
    assert _scan(frame)["C-trend"].states[78] == -1


def test_no_pattern_unknown_is_not_false_and_arrays_readonly() -> None:
    result = base_no_pattern(np.array([True, True, True, False]), np.array([-1, 0, 1, -1], dtype=np.int8))
    assert tuple(result.states) == (-1, 1, 0, 0)
    assert tuple(result.formula_states) == (-1, 1, 0, -1)
    assert result.raw_indices == (1,)
    with pytest.raises(ValueError):
        result.states[0] = 0


def test_p1_original_breakout_pairing_and_admission() -> None:
    frame = _frame()
    events = [DetectorEvent("P1", "P1", t, 200, 100, 100, 99, (("breakout_index", 220),)) for t in (230, 240)]
    result = scan_controls(Bars.from_frame(frame), base_eligible=np.ones(300, dtype=np.bool_), h1_source_events=(), p1_events=events)["C-P1-breakout"]
    assert result.raw_indices == (220,)
    assert result.paired_events == ((220, 230), (220, 240))


def test_p1_all_ancestors_keep_pairs_and_deduplicate_breakout_days() -> None:
    encoded = json.dumps([{"breakout_index": 210, "retest_index": 225, "resistance": 100}, {"breakout_index": 220, "retest_index": 225, "resistance": 100}])
    event = DetectorEvent("P1", "P1", 230, 200, 100, 100, 99, (("breakout_index", 220), ("alternate_ancestors", encoded)))
    eligible = np.ones(300, dtype=np.bool_)
    eligible[210] = False
    result = scan_controls(Bars.from_frame(_frame()), base_eligible=eligible, h1_source_events=(), p1_events=(event,))["C-P1-breakout"]
    assert result.paired_events == ((210, 230), (220, 230))
    assert result.formula_states[210] == 1 and result.states[210] == 0
    assert result.raw_indices == (220,)


@pytest.mark.parametrize("encoded", ("{", "{}", '[{"breakout_index":true}]', '[{"breakout_index":231}]'))
def test_p1_malformed_ancestor_audit_rejected(encoded: str) -> None:
    event = DetectorEvent("P1", "P1", 230, 200, 100, 100, 99, (("breakout_index", 220), ("alternate_ancestors", encoded)))
    with pytest.raises(ValueError, match="P1 alternate"):
        scan_controls(Bars.from_frame(_frame()), base_eligible=np.ones(300, dtype=np.bool_), h1_source_events=(), p1_events=(event,))


def test_suffix_does_not_change_past_controls() -> None:
    frame = _frame()
    before = _scan(frame)
    suffix = frame.iloc[-1:].copy()
    suffix.index += pd.Timedelta(days=1)
    after = _scan(pd.concat([frame, suffix]))
    for control in before:
        np.testing.assert_array_equal(before[control].states, after[control].states[:-1])


def test_bad_eligibility_and_source_index_fail_closed() -> None:
    with pytest.raises(ValueError, match="eligibility"):
        scan_controls(Bars.from_frame(_frame()), base_eligible=cast(Any, np.ones(300, dtype=np.int8)), h1_source_events=())
    with pytest.raises(ValueError, match="calendar"):
        _scan(_frame(), sources=({"t": -1},))

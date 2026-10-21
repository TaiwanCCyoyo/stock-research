from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_groups_v1 import PatternGroups, groups_for_pattern
from research_core.pattern_scan_stock_v1 import EVENT_COLUMNS


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[str, ...]]:
    dates = tuple(day.date().isoformat() for day in pd.date_range("2020-01-01", periods=300))
    rows = []
    for subtype, cohort, t in (("B1a", "B1a", 100), ("B1b", "B1b", 101), ("union", "union", 100)):
        row: dict[str, Any] = dict.fromkeys(EVENT_COLUMNS)
        row.update(
            security_id="TW:0001",
            event_id=EventIdentity("TW:0001", dates[t], "B1", subtype, "def.v1", "input.v1").event_id,
            t0=dates[t],
            calendar_index=t,
            pattern_id="B1",
            subtype_id=subtype,
            cohort_id=cohort,
            window_start=0,
            pivot=10.0,
            support=9.0,
            lower=8.0,
            definition_id="def.v1",
            input_id="input.v1",
            base_eligible=True,
        )
        rows.append(row)
    events = pd.DataFrame(rows, columns=pd.Index(EVENT_COLUMNS))
    controls = pd.DataFrame({"security_id": "TW:0001", "t0": dates, "calendar_index": np.arange(300)})
    for control in ("C-base", "C-52w", "C-dip", "C-trend", "C-nh", "C-P1-breakout"):
        states = np.ones(300, dtype=np.int8) if control == "C-base" else np.zeros(300, dtype=np.int8)
        if control != "C-base":
            states[260:262] = 1
        controls[control] = states
        controls[f"{control}:formula"] = states.copy()
        controls[f"{control}:cooled"] = np.isin(np.arange(300), np.arange(0, 300, 21) if control == "C-base" else [260])
    patterns = pd.DataFrame({
        "security_id": "TW:0001",
        "B1": np.zeros(300, dtype=np.int8),
        "B1:B1a": np.zeros(300, dtype=np.int8),
        "B1:B1b": np.zeros(300, dtype=np.int8),
    })
    patterns.loc[[100, 101], "B1"] = 1
    patterns.loc[100, "B1:B1a"] = 1
    patterns.loc[101, "B1:B1b"] = 1
    patterns.loc[105, "B1"] = -1
    universe = pd.DataFrame({"base_eligible": True, "eligibility_reason": None}, index=pd.RangeIndex(300))
    return events, controls, patterns, universe, dates


def _groups(inputs: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, tuple[str, ...]]) -> PatternGroups:
    return groups_for_pattern("B1", *inputs, "def.v1", "input.v1", security_id="TW:0001")


def test_pattern_subtypes_remain_independent_and_baseline_uses_raw_union() -> None:
    inputs = _inputs()
    result = _groups(inputs)
    assert result.events["pattern:B1a"].calendar_index.tolist() == [100]
    assert result.events["pattern:B1b"].calendar_index.tolist() == [101]
    assert result.events["pattern:union"].calendar_index.tolist() == [100]
    no_pattern = result.daily_states["C-base-no-pattern"]
    assert tuple(no_pattern.iloc[[100, 101, 105]]) == (0, 0, -1)
    assert 105 not in result.events["C-base-no-pattern"].calendar_index.tolist()
    assert 106 in result.events["C-base-no-pattern"].calendar_index.tolist()
    assert 105 in result.events["C-base-all"].calendar_index.tolist()


def test_control_ids_no_fake_support_and_daily_diagnostics_uncooldowned() -> None:
    inputs = _inputs()
    result = _groups(inputs)
    ids = []
    for control, start in (("C-52w", 10), ("C-dip", 200), ("C-trend", 181), ("C-nh", 240), ("C-P1-breakout", 200)):
        event = result.events[control].iloc[0]
        assert event.pattern_id == event.subtype_id == control
        assert event.event_id == EventIdentity("TW:0001", inputs[-1][260], control, control, "def.v1", "input.v1").event_id
        assert event.window_start == start
        assert event.pivot is None and event.support is None and event.lower is None
        ids.append(event.event_id)
    assert len(set(ids)) == len(ids)
    assert result.events["C-52w-daily"].calendar_index.tolist() == [260, 261]
    assert result.events["C-52w-daily"].event_id.iloc[0] == result.events["C-52w"].event_id.iloc[0]
    assert len(result.events["C-base-daily"]) == 300


def test_formula_unknown_retained_even_when_eligibility_excludes_day() -> None:
    inputs = _inputs()
    inputs[1].loc[259, "C-nh"] = 0
    inputs[1].loc[259, "C-nh:formula"] = -1
    inputs[3].loc[259, "base_eligible"] = False
    result = _groups(inputs)
    assert result.formula_states["C-nh"].iloc[259] == -1
    assert result.daily_states["C-nh"].iloc[259] == 0


def test_empty_cohorts_keep_schema_and_fixed_subtype_keys() -> None:
    events, controls, patterns, universe, dates = _inputs()
    result = _groups((events.iloc[:0], controls, patterns, universe, dates))
    for key in ("pattern:union", "pattern:B1a", "pattern:B1b"):
        assert result.events[key].empty and tuple(result.events[key].columns) == EVENT_COLUMNS


def test_p1_breakout_uses_original_control_date_without_confirmation_alias() -> None:
    events, controls, _, universe, dates = _inputs()
    patterns = pd.DataFrame({"P1": np.zeros(300, dtype=np.int8), "P1:P1": np.zeros(300, dtype=np.int8)})
    result = groups_for_pattern("P1", events.iloc[:0], controls, patterns, universe, dates, "def.v1", "input.v1", security_id="TW:0001")
    assert result.events["C-P1-breakout"].calendar_index.tolist() == [260]
    assert result.events["C-P1-breakout"].t0.tolist() == [dates[260]]
    assert "C-trend" in result.events


def test_misaligned_or_wrong_identity_tables_rejected() -> None:
    events, controls, patterns, universe, dates = _inputs()
    with pytest.raises(ValueError, match="aligned"):
        _groups((events, controls.iloc[:-1], patterns, universe, dates))
    events.loc[0, "input_id"] = "changed"
    with pytest.raises(ValueError, match="fixed identity"):
        _groups((events, controls, patterns, universe, dates))

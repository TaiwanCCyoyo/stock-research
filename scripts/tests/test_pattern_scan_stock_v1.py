"""One-stock integration and raw-member independent-clock wiring probes."""

import json
from typing import Any

import numpy as np
import pandas as pd

from research_core.pattern_scan_stock_v1 import assemble_cohorts, h1_values, stock_phase
from research_core.patterns.scan_contract_v1 import Bars, DetectorEvent, finish_scan


def prices(n: int = 380) -> pd.DataFrame:
    days = pd.bdate_range("2020-01-01", periods=n)
    t = np.arange(n)
    close = 30 + 0.1 * t + 2 * np.sin(t / 6)
    return pd.DataFrame(
        {
            "Open": close - 0.1,
            "High": close + 0.4,
            "Low": close - 0.4,
            "Close": close,
            "RawClose": close,
            "RawOpen": close - 0.1,
            "RawHigh": close + 0.4,
            "RawLow": close - 0.4,
            "VolumeLots": 1000.0,
            "Turnover": close * 1000,
            "Quality": True,
            "quality_reason": None,
        },
        index=days,
    )


def test_all_stock_outputs_and_causal_prefix_without_global_ranks() -> None:
    supplied = prices()
    before = supplied.copy(deep=True)
    arguments: dict[str, Any] = {
        "security_id": "TW:1101",
        "industry_ref": "synthetic",
        "ordinary_reference": True,
        "definition_id": "synthetic.v1",
        "input_id": "invented",
    }
    result = stock_phase(supplied, **arguments)
    shorter = stock_phase(supplied.iloc[:300], **arguments)
    pd.testing.assert_frame_equal(supplied, before)
    assert len(result.base_labels) == 2 * len(supplied)
    assert set(result.base_labels.horizon) == {126, 252}
    assert set(result.pattern_states.columns) >= {"H1", "B1", "B2", "B3", "B4", "R1", "R2", "R3", "P1", "L1", "L2", "L3"}
    assert "H" not in result.common_values and "J" not in result.common_values and "K3" not in result.common_values
    pd.testing.assert_frame_equal(result.pattern_states.iloc[:300], shorter.pattern_states)
    pd.testing.assert_frame_equal(result.common_values.iloc[:300], shorter.common_values)
    pd.testing.assert_frame_equal(
        result.raw_events.loc[result.raw_events.calendar_index.lt(300)].reset_index(drop=True), shorter.raw_events.reset_index(drop=True)
    )
    assert not result.universe.base_eligible.iloc[:59].any() and result.universe.base_eligible.iloc[59:].all()
    h1_events = result.cohort_events.loc[result.cohort_events.pattern_id.eq("H1")]
    if len(h1_events):
        values = h1_values(h1_events, result.indicators)
        assert len(values) == len(h1_events) and bool(values["B"].notna().all())


def test_union_uses_subtype_suppressed_raw_and_fixed_representative_metadata() -> None:
    bars = Bars.from_frame(prices(40).rename(columns={"VolumeLots": "Volume"}))
    states = np.zeros((40, 2), dtype=np.int8)
    events = []
    for subtype, col, days in (("B1a", 0, (0, 20)), ("B1b", 1, (1, 21))):
        for t in days:
            states[t, col] = 1
            events.append(DetectorEvent("B1", subtype, t, 0, 10.0 + col, 8.0 + col, 7.0 + col))
    scan = finish_scan("B1", ("B1a", "B1b"), states, events, ())
    qualification = pd.DataFrame({"base_eligible": True, "eligibility_reason": None}, index=prices(40).index)
    raw, kept = assemble_cohorts((scan,), bars, "TW:1101", "v1", "input", qualification)
    assert kept.loc[kept.cohort_id.eq("B1a"), "calendar_index"].tolist() == [0]
    assert kept.loc[kept.cohort_id.eq("B1b"), "calendar_index"].tolist() == [1]
    union = kept.loc[kept.cohort_id.eq("union")]
    assert union.calendar_index.tolist() == [0, 21]
    assert union.support.tolist() == [8.0, 9.0]
    assert not raw.loc[raw.calendar_index.eq(21), "subtype_retained"].item()
    assert json.loads(union.member_subtype_ids.iloc[1]) == ["B1b"]
    assert union.event_id.is_unique


def test_same_day_all_members_and_single_subtype_union_is_not_doubled() -> None:
    bars = Bars.from_frame(prices(40).rename(columns={"VolumeLots": "Volume"}))
    states = np.zeros((40, 2), dtype=np.int8)
    states[3] = 1
    events = [DetectorEvent("B1", sub, 3, 0, 10.0, support, 7.0) for sub, support in (("B1a", 8.0), ("B1b", 9.0))]
    scan = finish_scan("B1", ("B1b", "B1a"), states, events, ())
    single_states = np.zeros((40, 1), dtype=np.int8)
    single_states[3] = 1
    single = finish_scan("B4", ("B4",), single_states, [DetectorEvent("B4", "B4", 3, 0, 10.0, 8.0, 7.0)], ())
    qualification = pd.DataFrame({"base_eligible": False, "eligibility_reason": "synthetic_excluded"}, index=prices(40).index)
    _, kept = assemble_cohorts((scan, single), bars, "TW:0051", "v1", "input", qualification)
    union = kept.loc[kept.pattern_id.eq("B1") & kept.cohort_id.eq("union")].iloc[0]
    assert union.support == 9.0 and json.loads(union.member_subtype_ids) == ["B1b", "B1a"]
    assert len(json.loads(union.member_metadata)) == 2
    assert len(kept.loc[kept.pattern_id.eq("B4")]) == 1
    assert not kept.base_eligible.any()  # Raw clocks keep eligibility exclusions auditable.

"""Legitimate daily N/A remains Q4 unknown without changing legacy v1."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_candidate_daily_v1 import daily_candidate_states as legacy_states
from research_core.pattern_scan_candidate_daily_v2 import daily_candidate_states
from research_core.pattern_scan_episode_coverage_v1 import observe_episode
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern, event_conditions
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_events_v1 import Episode
from research_core.pattern_scan_reporting_v1 import candidate_membership


def _inputs(target: str = "B1", *, bonus: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray]:
    calendar = pd.bdate_range("2020-01-02", periods=120)
    indicators = pd.DataFrame({"Close": 100.0, "Low": 80.0}, index=calendar)
    common = pd.DataFrame(
        {
            "security_id": "TW:0001",
            "t0": calendar.strftime("%Y-%m-%d"),
            "calendar_index": np.arange(len(calendar)),
            "definition_id": "synthetic-definition",
            "input_id": "synthetic-input",
            "H": 95.0,
            "H_applicable": True,
            "MA_b": True,
            "G": 1.2,
        },
        index=calendar,
    )
    raw = np.zeros(len(calendar), dtype=np.int8)
    raw[[30, 60]] = 1
    source = {
        "restart": 10,
        "seq": [{"k": "H", "rel": "higher", "p": 110.0, "i": 20}, {"k": "L", "rel": "higher", "p": 90.0, "i": 25}],
        "bonus_levels": [{"age": "old", "level": 120.0}] if bonus else [],
        "cat": "hhhl",
        "big_hhhl": False,
        "vx": 3.4,
    }
    events: list[dict[str, Any]] = []
    for position in (30, 60):
        t0 = str(calendar[position].strftime("%Y-%m-%d"))
        identity = EventIdentity("TW:0001", t0, target, "first", "synthetic-definition", "synthetic-input")
        events.append({
            "event_id": identity.event_id,
            "security_id": "TW:0001",
            "t0": t0,
            "calendar_index": position,
            "pattern_id": target,
            "subtype_id": "first",
            "definition_id": "synthetic-definition",
            "input_id": "synthetic-input",
            "support": 99.0,
            "pivot": 95.0,
            "details_json": json.dumps({"source_event_json": json.dumps(source)}),
        })
    return pd.DataFrame(events), indicators, common, raw


def _atom(target: str, feature: str, bin_id: str) -> Atom:
    return next(atom for atom in atoms_for_pattern(target) if atom.feature_id == feature and atom.bin_id == bin_id)


def _arguments(candidates: dict[str, tuple[Atom, ...]]) -> dict[str, Any]:
    return {"security_id": "TW:0001", "definition_id": "synthetic-definition", "input_id": "synthetic-input", "candidates": candidates}


def test_b1_h_not_applicable_dominates_false_atom_then_becomes_daily_unknown() -> None:
    events, indicators, common, raw = _inputs()
    common["H_applicable"] = False
    common["MA_b"] = False
    h = _atom("B1", "H", "ge90")
    ma = _atom("B1", "MA_b", "true")
    candidates: dict[str, tuple[Atom, ...]] = {"h": (h,), "h-and-false-ma": (h, ma)}
    classified = event_conditions(events, indicators, common, target_pattern="B1")
    np.testing.assert_array_equal(candidate_membership(classified, (ma,)), np.array([0, 0], dtype=np.int8))
    np.testing.assert_array_equal(candidate_membership(classified, (h, ma)), np.array([-2, -2], dtype=np.int8))
    result = daily_candidate_states("B1", events, indicators, common, raw, **_arguments(candidates))
    for values in result.values():
        assert values[30] == values[60] == -1
        assert np.all(values[raw == 0] == 0)
        assert values.dtype == np.int8
    with pytest.raises(ValueError, match="not applicable"):
        legacy_states("B1", events, indicators, common, raw, **_arguments(candidates))


def test_h1_without_bonus_levels_is_unknown_in_v2_and_still_rejected_by_v1() -> None:
    inputs = _inputs("H1", bonus=False)
    candidates: dict[str, tuple[Atom, ...]] = {"overhead": (_atom("H1", "A", "lt10"),)}
    result = daily_candidate_states("H1", *inputs, **_arguments(candidates))["overhead"]
    assert result[30] == result[60] == -1
    assert np.all(result[inputs[3] == 0] == 0)
    with pytest.raises(ValueError, match="not applicable"):
        legacy_states("H1", *inputs, **_arguments(candidates))


@pytest.mark.parametrize("target", ("B1", "H1"))
def test_all_applicable_values_equal_legacy_and_inputs_remain_unchanged(target: str) -> None:
    events, indicators, common, raw = _inputs(target)
    raw[10] = -1
    common.iloc[60, common.columns.get_loc("MA_b")] = False
    candidates: dict[str, tuple[Atom, ...]] = {
        "ma": (_atom(target, "MA_b", "true"),),
        "support": (_atom(target, "SR_support", "lt05"),),
        "relative-strength": (_atom(target, "H", "ge90"),),
    }
    if target == "H1":
        candidates["overhead"] = (_atom(target, "A", "lt10"),)
    before_frames = [frame.copy(deep=True) for frame in (events, indicators, common)]
    before_raw = raw.copy()
    expected = legacy_states(target, events, indicators, common, raw, **_arguments(candidates))
    actual = daily_candidate_states(target, events, indicators, common, raw, **_arguments(candidates))
    assert tuple(actual) == tuple(expected) == tuple(candidates)
    for name, values in actual.items():
        np.testing.assert_array_equal(values, expected[name])
        assert values.dtype == np.int8 and not values.flags.writeable
    assert actual["ma"][30] == 1 and actual["ma"][60] == 0
    assert actual["relative-strength"][10] == -1
    for frame, before in zip((events, indicators, common), before_frames, strict=True):
        pd.testing.assert_frame_equal(frame, before)
    np.testing.assert_array_equal(raw, before_raw)


@pytest.mark.parametrize(
    "unknown_at,retained,status,timing_certain",
    ((30, None, "unknown", False), (30, 60, "matched", False), (60, 30, "matched", True)),
)
def test_q4_unknown_no_match_and_match_absorption_keep_first_timing_uncertainty(
    unknown_at: int,
    retained: int | None,
    status: str,
    timing_certain: bool,
) -> None:
    events, indicators, common, raw = _inputs()
    common.iloc[unknown_at, common.columns.get_loc("H_applicable")] = False
    candidates: dict[str, tuple[Atom, ...]] = {"h": (_atom("B1", "H", "ge90"),)}
    states = daily_candidate_states("B1", events, indicators, common, raw, **_arguments(candidates))["h"]
    episode = Episode((40,), 40, 90, "known")
    closes = [100.0] * len(raw)
    closes[90] = 200.0
    result = observe_episode(episode, closes, [] if retained is None else [retained], states.tolist())
    assert result["coverage_status"] == status
    assert result["first_timing_certain"] is timing_certain
    assert result["window_calendar_full"] is True
    assert result["window_states_known"] is False
    assert result["first_matching_index"] == retained


def test_wrong_raw_event_identity_is_still_rejected() -> None:
    events, indicators, common, raw = _inputs()
    events.loc[0, "event_id"] = "different-event-identity"
    candidates: dict[str, tuple[Atom, ...]] = {"ma": (_atom("B1", "MA_b", "true"),)}
    with pytest.raises(ValueError, match="fixed identity"):
        daily_candidate_states("B1", events, indicators, common, raw, **_arguments(candidates))

from __future__ import annotations

import json
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_candidate_daily_v1 import daily_candidate_states
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern
from research_core.pattern_scan_event_outcomes_v1 import EventIdentity


def _inputs(target: str = "B1") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray]:
    dates = pd.date_range("2020-01-01", periods=50)
    indicators = pd.DataFrame({"Close": 100.0, "Low": 80.0}, index=dates)
    common = pd.DataFrame({"G": 1.2, "MA_b": True}, index=dates)
    raw = np.zeros(50, dtype=np.int8)
    raw[30:32] = 1
    source = {
        "restart": 10,
        "seq": [{"k": "H", "rel": "higher", "p": 110.0, "i": 20}, {"k": "L", "rel": "higher", "p": 90.0, "i": 25}],
        "bonus_levels": [{"age": "old", "level": 120.0}],
        "cat": "hhhl",
        "big_hhhl": False,
        "vx": 3.4,
    }
    events: list[dict[str, Any]] = []
    for t, subtype, support in ((30, "first", 99.0), (31, "first", 99.0), (31, "second", 80.0)):
        date = cast(pd.Timestamp, dates[t]).strftime("%Y-%m-%d")
        identity = EventIdentity("TW:0001", date, target, subtype, "def.v1", "input.v1")
        events.append({
            "event_id": identity.event_id,
            "security_id": "TW:0001",
            "t0": date,
            "calendar_index": t,
            "pattern_id": target,
            "subtype_id": subtype,
            "definition_id": "def.v1",
            "input_id": "input.v1",
            "support": support,
            "pivot": 95.0,
            "details_json": json.dumps({"source_event_json": json.dumps(source)}),
        })
    return pd.DataFrame(events), indicators, common, raw


def _atom(target: str, feature: str, bin_id: str) -> Atom:
    return next(atom for atom in atoms_for_pattern(target) if atom.feature_id == feature and atom.bin_id == bin_id)


def _run(inputs: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, np.ndarray], target: str, atom: Atom) -> np.ndarray:
    return daily_candidate_states(
        target, *inputs, security_id="TW:0001", definition_id="def.v1", input_id="input.v1", candidates={"invented-candidate": (atom,)}
    )["invented-candidate"]


def test_raw_suppressed_day_and_first_member_support_are_retained() -> None:
    inputs = _inputs()
    before = inputs[0].copy(deep=True)
    result = _run(inputs, "B1", _atom("B1", "SR_support", "lt05"))
    assert tuple(result[30:32]) == (1, 1)
    assert np.flatnonzero(result == 1).tolist() == [30, 31]
    pd.testing.assert_frame_equal(inputs[0], before)
    with pytest.raises(ValueError):
        result[30] = 0


def test_h1_uses_raw_source_volume_instead_of_common_volume() -> None:
    inputs = _inputs("H1")
    result = _run(inputs, "H1", _atom("H1", "G", "300to500"))
    assert tuple(result[30:32]) == (1, 1)
    assert inputs[2].G.eq(1.2).all()


def test_unknown_absorption_and_known_false_without_fake_support() -> None:
    events, indicators, common, raw = _inputs()
    raw[10:13] = -1
    common["MA_b"] = common.MA_b.astype(object)
    common.iloc[10, common.columns.get_loc("MA_b")] = False
    common.iloc[11, common.columns.get_loc("MA_b")] = None
    common.iloc[13, common.columns.get_loc("MA_b")] = None
    result = _run((events, indicators, common, raw), "B1", _atom("B1", "MA_b", "true"))
    assert tuple(result[10:14]) == (0, -1, -1, 0)
    support = _run((events, indicators, common, raw), "B1", _atom("B1", "SR_support", "lt05"))
    assert tuple(support[10:14]) == (-1, -1, -1, 0)


def test_nonapplicable_selected_atom_on_true_event_rejected() -> None:
    events, indicators, common, raw = _inputs("H1")
    for index in events.index:
        details = json.loads(events.details_json.iloc[index])
        source = json.loads(details["source_event_json"])
        source["bonus_levels"] = []
        events.loc[index, "details_json"] = json.dumps({"source_event_json": json.dumps(source)})
    atom = next(atom for atom in atoms_for_pattern("H1") if atom.feature_id == "A")
    with pytest.raises(ValueError, match="not applicable"):
        _run((events, indicators, common, raw), "H1", atom)


@pytest.mark.parametrize("damage", ("definition", "input", "coverage", "calendar"))
def test_wrong_pins_or_missing_raw_true_coverage_rejected(damage: str) -> None:
    events, indicators, common, raw = _inputs()
    if damage in {"definition", "input"}:
        events[f"{damage}_id"] = "changed"
    elif damage == "coverage":
        events = events.loc[events.calendar_index.ne(30)]
    else:
        common.index += pd.Timedelta(days=1)
    with pytest.raises(ValueError):
        _run((events, indicators, common, raw), "B1", _atom("B1", "MA_b", "true"))


def test_future_suffix_leaves_past_observations_identical() -> None:
    events, indicators, common, raw = _inputs()
    atom = _atom("B1", "SR_support", "lt05")
    before = _run((events, indicators, common, raw), "B1", atom)
    additions = []
    for frame in (indicators, common):
        suffix = frame.iloc[-1:].copy()
        suffix.index += pd.Timedelta(days=1)
        additions.append(pd.concat([frame, suffix]))
    after = _run((events, additions[0], additions[1], np.r_[raw, np.int8(0)]), "B1", atom)
    np.testing.assert_array_equal(before, after[:-1])

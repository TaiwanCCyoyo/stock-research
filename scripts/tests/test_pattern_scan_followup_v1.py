from __future__ import annotations

import json
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_observations import classify_window
from research_core.pattern_scan_followup_v1 import FIRST_COLUMNS, OBSERVATION_COLUMNS, PATH_COLUMNS, followup_values


def _frame() -> pd.DataFrame:
    return pd.DataFrame({"Close": 100.0, "SMA20": 100.0, "SMA60": 100.0, "BBLower": 100.0}, index=pd.bdate_range("2020-01-01", periods=9))


def _pivots(frame: pd.DataFrame, highs: list[tuple[int, int, float]] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        [(1.5, "high", extreme, confirmed, frame.index[extreme], frame.index[confirmed], price) for extreme, confirmed, price in highs or []],
        columns=pd.Index(["k", "kind", "extreme_index", "confirmation_index", "extreme_date", "confirmed_at", "price"]),
    )


def _events(frame: pd.DataFrame, *, t0: int = 2, horizon: int = 5) -> pd.DataFrame:
    observation = classify_window(cast(pd.Series, frame["Close"]).to_numpy(dtype=float).tolist()[t0:], horizon)
    return pd.DataFrame([
        {
            "security_id": "0001",
            "event_id": "event-1",
            "t0": cast(pd.Timestamp, frame.index[t0]).date().isoformat(),
            "calendar_index": t0,
            "horizon": horizon,
            "pattern_id": "R1",
            "subtype_id": "R1a",
            "cohort_id": "union",
            "base_label": observation.outcome,
            "effective_label": observation.outcome,
            "calendar_full": observation.calendar_full,
            "base_main_eligible": observation.main_eligible,
            "event_main_eligible": observation.main_eligible,
            "event_eligibility_excluded": False,
            "support": 90.0,
            "lower": 80.0,
            "confirmed_support": 95.0,
            "base_first_hit_offset": observation.first_hit_offset,
            "base_label_version_id": "base.v1",
            "base_label_manifest_sha256": "synthetic-pin",
            "detection_quality_reasons_json": "[]",
            "result_quality_reasons_json": "[]",
            "event_eligibility_reasons_json": "[]",
            "effective_unknown_reasons_json": "[]",
        }
    ])


def _row(frame: pd.DataFrame, flag: str | None = None, *, landmark: int | None = None) -> Any:
    filtered = frame
    if flag is not None:
        filtered = filtered.loc[cast(pd.Series, filtered["flag_id"]).eq(flag)]
    if landmark is not None:
        filtered = filtered.loc[cast(pd.Series, filtered["landmark"]).eq(landmark)]
    return cast(Any, filtered.iloc[0])


def test_paths_full_flags_and_landmarks_preserve_independent_populations() -> None:
    frame = _frame()
    frame.loc[frame.index[3], "Close"] = 85
    outputs = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=(2,))
    assert len(outputs.paths) == len(outputs.first_flags) == 1
    assert len(outputs.flags) == len(outputs.landmarks) == 9
    path = _row(outputs.paths)
    assert path["path_category"] == "direct_failure"
    assert path["base_label"] == path["effective_label"] == "flat-win"
    assert path["calendar_full"] and path["event_main_eligible"]
    assert path["first_minus_10_offset"] == 1
    flag = _row(outputs.flags, "X6_10")
    assert flag["first_trigger_offset"] == 1 and flag["trigger_return"] == pytest.approx(-0.15)
    landmark = _row(outputs.landmarks, "Y1")
    assert landmark["riskset_id"] == "new_no_hit_valid_prefix" and landmark["riskset_eligible"]
    assert landmark["base_label"] == "flat-win"


def test_first_flag_ties_use_fixed_id_order_and_retain_all_same_day_flags() -> None:
    frame = _frame()
    frame.loc[frame.index[3], "Close"] = 85
    outputs = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=())
    first = _row(outputs.first_flags)
    assert first["first_flag_state"] == "triggered"
    assert first["first_flag_offset"] == 1
    ties = json.loads(first["first_flag_all_flag_ids_json"])
    assert ties == sorted(["Y1", "Y3", "X5_MA20", "X5_MA60", "X6_10", "X6_15", "X7"])
    assert first["first_flag_flag_id"] == ties[0] == "X5_MA20"
    assert first["first_flag_flag_id_certain"]


def test_earlier_unknown_blocks_claiming_a_later_certain_first_flag() -> None:
    frame = _frame()
    frame.loc[frame.index[3], "SMA20"] = np.nan
    frame.loc[frame.index[4], "Close"] = 85
    outputs = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=())
    first = _row(outputs.first_flags)
    assert first["first_flag_state"] == "unknown" and pd.isna(first["first_flag_offset"])
    assert first["first_flag_unknown_reason"] == "missing_before_trigger"
    assert first["first_flag_first_observed_offset"] == 2
    assert _row(outputs.flags, "X5_MA20")["flag_state"] == "unknown"
    assert _row(outputs.flags, "Y1")["flag_state"] == "triggered"


def test_missing_after_first_trigger_does_not_erase_flag_but_full_path_is_unknown() -> None:
    frame = _frame()
    frame.loc[frame.index[3], "Close"] = 85
    frame.loc[frame.index[4], "Close"] = np.nan
    outputs = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=())
    assert _row(outputs.first_flags)["first_flag_state"] == "triggered"
    assert _row(outputs.paths)["path_category"] == "unknown"
    assert _row(outputs.paths)["base_label"] == "unknown"
    assert _row(outputs.flags, "Y1")["flag_state"] == "triggered"


def test_hit_with_later_missing_stays_base_hit_while_path_is_unknown() -> None:
    frame = _frame()
    frame.loc[frame.index[3], "Close"] = 200
    frame.loc[frame.index[4], "Close"] = np.nan
    events = _events(frame)
    outputs = followup_values(events, frame, _pivots(frame), horizons=(5,), landmarks=(2,))
    path = _row(outputs.paths)
    assert path["base_label"] == path["effective_label"] == "hit"
    assert path["path_category"] == "unknown"
    assert _row(outputs.landmarks, "Y1")["riskset_state"] == "early_unknown"
    assert _row(outputs.first_flags)["before_hit_first_flag_state"] == "all_false"


@pytest.mark.parametrize("hit_offset", [1, 2])
def test_hit_before_or_on_landmark_is_not_in_new_riskset(hit_offset: int) -> None:
    frame = _frame()
    frame.loc[frame.index[2 + hit_offset], "Close"] = 200
    frame.loc[frame.index[2 + hit_offset], "SMA20"] = 210
    outputs = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=(2,))
    row = _row(outputs.landmarks, "X5_MA20")
    assert row["riskset_state"] == "early_hit" and not row["riskset_eligible"]
    assert row["flag_state"] == "all_false"
    assert row["raw_flag_state"] == "triggered"
    assert row["clock_first_hit_offset"] == hit_offset


def test_quality_overlay_keeps_base_and_numeric_diagnostics_without_rate_eligibility() -> None:
    frame = _frame()
    frame.loc[frame.index[4], "Close"] = 200
    events = _events(frame)
    events.loc[0, "effective_label"] = "unknown"
    events.loc[0, "event_main_eligible"] = False
    events.loc[0, "result_quality_reasons_json"] = '["unexplained_jump"]'
    events.loc[0, "effective_unknown_reasons_json"] = '["result:unexplained_jump"]'
    outputs = followup_values(events, frame, _pivots(frame), horizons=(5,), landmarks=(2,))
    for table in (outputs.paths, outputs.flags, outputs.landmarks, outputs.first_flags):
        row = _row(table)
        assert row["base_label"] == "hit" and row["effective_label"] == "unknown"
        assert not row["event_main_eligible"]
        assert row["result_quality_reasons_json"] == '["unexplained_jump"]'
    assert _row(outputs.paths)["path_category"] == "rise_then_fall"


def test_missing_control_levels_are_unknown_without_invented_support() -> None:
    frame = _frame()
    events = _events(frame)
    events.loc[0, ["support", "lower", "confirmed_support"]] = np.nan
    outputs = followup_values(events, frame, _pivots(frame), horizons=(5,), landmarks=())
    assert all(_row(outputs.flags, flag)["flag_state"] == "unknown" for flag in ("Y1", "Y2", "Y3"))
    assert _row(outputs.flags, "X6_10")["flag_state"] == "all_false"
    assert _row(outputs.first_flags)["first_flag_state"] == "unknown"


def test_lower_high_metadata_uses_actual_confirmation_clock() -> None:
    frame = _frame()
    pivots = _pivots(frame, [(0, 1, 130), (3, 5, 120)])
    outputs = followup_values(_events(frame), frame, pivots, horizons=(5,), landmarks=(2,))
    flag = _row(outputs.flags, "X8")
    assert flag["first_trigger_offset"] == 3
    assert _row(outputs.landmarks, "X8")["flag_state"] == "all_false"
    first = json.loads(_row(outputs.paths)["first_lower_high_json"])
    assert first["metadata"]["extreme_index"] == 3
    assert first["metadata"]["confirmation_index"] == 5
    assert _row(outputs.first_flags)["first_flag_offset"] == 3


def test_landmark_return_stratum_is_independent_of_final_outcome_and_flag_state() -> None:
    frame = _frame()
    frame.loc[frame.index[4], "Close"] = 125
    frame.loc[frame.index[7], "Close"] = 90
    outputs = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=(2,))
    row = _row(outputs.landmarks, "X6_10")
    assert row["rise_bin"] == "ge1p25"
    assert row["base_label"] == row["effective_label"] == "loss"
    assert row["flag_state"] == "all_false"
    assert _row(outputs.flags, "X6_10")["flag_state"] == "triggered"


def test_base_label_or_first_hit_mismatch_fails_closed() -> None:
    frame = _frame()
    events = _events(frame)
    events.loc[0, "base_label"] = "hit"
    with pytest.raises(ValueError, match="base label"):
        followup_values(events, frame, _pivots(frame), horizons=(5,))
    events = _events(frame)
    events.loc[0, "base_first_hit_offset"] = 2
    with pytest.raises(ValueError, match="first-hit"):
        followup_values(events, frame, _pivots(frame), horizons=(5,))


def test_empty_events_and_no_landmarks_keep_precise_schema() -> None:
    frame = _frame()
    outputs = followup_values(_events(frame).iloc[:0], frame, _pivots(frame), horizons=(5,))
    assert tuple(outputs.paths.columns) == PATH_COLUMNS
    assert tuple(outputs.flags.columns) == tuple(outputs.landmarks.columns) == OBSERVATION_COLUMNS
    assert tuple(outputs.first_flags.columns) == FIRST_COLUMNS
    assert all(table.empty for table in (outputs.paths, outputs.flags, outputs.landmarks, outputs.first_flags))
    nonempty = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=())
    assert nonempty.landmarks.empty and tuple(nonempty.landmarks.columns) == OBSERVATION_COLUMNS


def test_censored_path_and_flag_window_preserve_effective_unknown() -> None:
    frame = _frame().iloc[:5]
    outputs = followup_values(_events(frame), frame, _pivots(frame), horizons=(5,), landmarks=(2,))
    assert _row(outputs.paths)["path_reason"] == "incomplete_window"
    assert not _row(outputs.paths)["calendar_full"]
    assert _row(outputs.paths)["base_label"] == _row(outputs.paths)["effective_label"] == "unknown"
    assert _row(outputs.flags, "X6_10")["unknown_reason"] == "window_end"

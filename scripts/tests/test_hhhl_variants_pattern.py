"""Only invented frozen-event-shaped records and supplied price arrays."""

import json
from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_daily import bin_columns
from research_core.hhhl_variants_pattern import pattern_feature_values


def sample():
    calendar = pd.bdate_range("2020-01-06", periods=6)
    events = pd.DataFrame(
        [
            {
                "calendar_index": 5,
                "restart_date": calendar[1],
                "Z2": 100.0,
                "hz_top": 110.0,
                "bonus_levels": json.dumps([{"age": "old", "level": 150}, {"age": "recent_far", "level": 120}]),
                "pivot_sequence": json.dumps([
                    {"k": "H", "rel": "higher", "p": 108, "date": cast(pd.Timestamp, calendar[2]).date().isoformat()},
                    {"k": "L", "rel": "lower", "p": 90, "date": cast(pd.Timestamp, calendar[3]).date().isoformat()},
                ]),
                "cat": "hhhl",
                "big_hhhl": True,
                "vx": 1.25,
                "has_old": True,
                "has_recent_far": True,
            }
        ],
        index=pd.Index(["original-event-id"]),
    )
    return events, calendar, np.full(6, 80.0), np.full(6, 95.0)


def test_pattern_formulas_negative_distances_and_nearest_bonus():
    events, calendar, low, close = sample()
    original = events.copy(deep=True)
    result = pattern_feature_values(events, calendar, low, close)
    row = result.iloc[0]
    assert row.A == pytest.approx(120 / 95 - 1)
    assert row.B == pytest.approx(95 / 100 - 1)
    assert row.B2 == pytest.approx(95 / 110 - 1)
    assert row.E == 4
    assert row.E2 == pytest.approx(30 / 110)
    assert row.E3 == 1
    assert row.E4_cat == "hhhl"
    assert bool(row.E4_big)
    assert row.G == 1.25
    assert bool(row.A_applicable)
    assert result.index.equals(events.index)
    pd.testing.assert_frame_equal(events, original)
    binned = bin_columns(result)
    assert binned.B_bin.iloc[0] == "lt05"
    assert binned.B2_bin.iloc[0] == "lt03"
    assert binned.E3_bin.iloc[0] == "one"
    assert binned.G_bin.iloc[0] == "lt150"


def test_clean_no_bonus_and_zero_higher_points_are_distinct_from_missing():
    events, calendar, low, close = sample()
    events.loc[:, "bonus_levels"] = "[]"
    events.loc[:, "pivot_sequence"] = "[]"
    events.loc[:, ["has_old", "has_recent_far"]] = False
    result = pattern_feature_values(events, calendar, low, close)
    assert not bool(result.A_applicable.iloc[0])
    assert result.A.isna().all()
    assert result.E3.iloc[0] == 0
    binned = bin_columns(result)
    assert binned.A_status.iloc[0] == "not_applicable"
    assert binned.E3_bin.iloc[0] == "zero"


def test_missing_restart_low_and_support_have_explicit_unknown_reasons():
    events, calendar, low, close = sample()
    low[1] = np.nan
    events.loc[:, "Z2"] = np.nan
    result = pattern_feature_values(events, calendar, low, close)
    assert pd.isna(result.E2.iloc[0])
    assert result.E2_unknown_reason.iloc[0] == "missing_restart_low"
    assert result.B_unknown_reason.iloc[0] == "invalid_support"
    binned = bin_columns(result)
    assert binned.E2_status.iloc[0] == "feature_unknown"
    assert binned.E2_reason.iloc[0] == "missing_restart_low"
    assert binned.B_status.iloc[0] == "feature_unknown"


@pytest.mark.parametrize("bonus", [95, 90, 0, np.inf])
def test_nonupper_or_invalid_bonus_is_a_contract_error(bonus: float):
    events, calendar, low, close = sample()
    events.loc[:, "bonus_levels"] = json.dumps([{"age": "old", "level": bonus}])
    with pytest.raises(ValueError, match="bonus"):
        pattern_feature_values(events, calendar, low, close)


def test_future_extreme_and_future_restart_are_rejected():
    events, calendar, low, close = sample()
    events.loc[:, "calendar_index"] = 3
    seq = json.loads(events.pivot_sequence.iloc[0])
    seq[0]["date"] = cast(pd.Timestamp, calendar[4]).date().isoformat()
    events.loc[:, "pivot_sequence"] = json.dumps(seq)
    with pytest.raises(ValueError, match="extreme date"):
        pattern_feature_values(events, calendar, low, close)
    events.loc[:, "pivot_sequence"] = "[]"
    events.loc[:, "restart_date"] = calendar[4]
    with pytest.raises(ValueError, match="restart_date"):
        pattern_feature_values(events, calendar, low, close)


@pytest.mark.parametrize("position", [-1, 6, 1.5, True])
def test_invalid_event_calendar_index(position: object):
    events, calendar, low, close = sample()
    events["calendar_index"] = position
    with pytest.raises(ValueError, match="calendar_index"):
        pattern_feature_values(events, calendar, low, close)


def test_shape_empty_rows_and_date_identity_validation():
    events, calendar, low, close = sample()
    with pytest.raises(ValueError, match="arrays"):
        pattern_feature_values(events, calendar, low[:-1], close)
    empty = pattern_feature_values(events.iloc[:0], calendar, low, close)
    assert empty.empty
    assert empty.index.equals(events.iloc[:0].index)
    events["Date"] = calendar[4]
    with pytest.raises(ValueError, match="does not match"):
        pattern_feature_values(events, calendar, low, close)

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd
import pytest

import research_core.pattern_scan_flags_v1 as flag_module
from research_core.pattern_scan_flags_v1 import FLAG_IDS, event_flag_observations, event_flags

PIVOT_COLUMNS = ("k", "kind", "extreme_index", "confirmation_index", "extreme_date", "confirmed_at", "price")


def _frame(rows: int = 12) -> pd.DataFrame:
    return pd.DataFrame({"Close": 100.0, "SMA20": 100.0, "SMA60": 100.0, "BBLower": 100.0}, index=pd.bdate_range("2020-01-01", periods=rows))


def _pivots(frame: pd.DataFrame, values: list[tuple[str, int, int, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [(1.5, kind, extreme, confirmed, frame.index[extreme], frame.index[confirmed], price) for kind, extreme, confirmed, price in values],
        columns=pd.Index(PIVOT_COLUMNS),
    )


def _row(flags: pd.DataFrame, offset: int, column: str) -> bool | None:
    value = flags.loc[offset, column]
    return None if pd.isna(value) else bool(value)


def test_all_flags_have_future_offsets_only_and_nullable_boolean_dtype() -> None:
    frame = _frame()
    result = event_flags(frame, _pivots(frame, []), 3, support=110, lower=105)
    assert tuple(result.columns) == FLAG_IDS
    assert result.index.tolist() == list(range(1, 9))
    assert all(str(dtype) == "boolean" for dtype in result.dtypes)
    assert 0 not in result.index
    assert _row(result, 1, "Y1") is True
    assert _row(result, 1, "Y2") is True


@pytest.mark.parametrize("flag", ["Y1", "Y2", "Y3", "X5_MA20", "X5_MA60", "X7"])
def test_support_ma_and_bb_strict_equality(flag: str) -> None:
    frame = _frame()
    frame.loc[frame.index[1], "Close"] = 99
    frame.loc[frame.index[2], "Close"] = 98.999
    kwargs = {"support": 99.0, "lower": 99.0, "confirmed_support": 99.0}
    frame.loc[:, ["SMA20", "SMA60", "BBLower"]] = 99
    result = event_flags(frame, _pivots(frame, []), 0, **kwargs)
    assert _row(result, 1, flag) is False
    assert _row(result, 2, flag) is True


@pytest.mark.parametrize("flag,boundary", [("X6_10", 90.0), ("X6_15", 85.0)])
def test_drawdown_inclusive_equality_is_fixed_to_anchor(flag: str, boundary: float) -> None:
    frame = _frame()
    frame.loc[frame.index[1], "Close"] = boundary + 0.001
    frame.loc[frame.index[2], "Close"] = boundary
    frame.loc[frame.index[3], "Close"] = 200
    frame.loc[frame.index[4], "Close"] = boundary
    result = event_flags(frame, _pivots(frame, []), 0)
    assert _row(result, 1, flag) is False
    assert _row(result, 2, flag) is True
    assert _row(result, 4, flag) is True


def test_y3_nearest_confirmed_lower_low_is_fixed_at_t0() -> None:
    frame = _frame()
    frame.loc[frame.index[4], "Close"] = 95
    frame.loc[frame.index[5], "Close"] = 94
    pivots = _pivots(frame, [("low", 0, 1, 90), ("low", 1, 2, 95), ("low", 2, 3, 95), ("low", 4, 5, 99)])
    result = event_flags(frame, pivots, 3)
    assert result.attrs["confirmed_support"] == 95
    assert result.attrs["confirmed_support_source"] == "confirmed_nearest_pivot"
    assert result.attrs["confirmed_support_pivot"]["confirmed"] == 3
    assert _row(result, 1, "Y3") is False
    assert _row(result, 2, "Y3") is True


@pytest.mark.parametrize("provided,expected_flag,matching_pivot", [(94.0, False, False), (95.0, True, True)])
def test_caller_confirmed_support_has_truthful_source_metadata(provided: float, expected_flag: bool, matching_pivot: bool) -> None:
    frame = _frame()
    frame.loc[frame.index[3], "Close"] = 94.5
    pivots = _pivots(frame, [("low", 0, 1, 95)])
    result = event_flags(frame, pivots, 2, confirmed_support=provided)
    assert _row(result, 1, "Y3") is expected_flag
    assert result.attrs["confirmed_support"] == provided
    assert result.attrs["confirmed_support_source"] == "caller"
    metadata = result.attrs["confirmed_support_pivot"]
    if matching_pivot:
        assert metadata["price"] == provided
    else:
        assert metadata is None


def test_missing_fixed_levels_are_unknown_and_zero_levels_rejected() -> None:
    frame = _frame()
    result = event_flags(frame, _pivots(frame, []), 0)
    assert bool(result[["Y1", "Y2", "Y3"]].isna().to_numpy().all())
    with pytest.raises(ValueError, match="positive finite"):
        event_flags(frame, _pivots(frame, []), 0, support=0)


def test_x8_waits_for_confirmation_and_reports_extreme_and_confirmation_dates() -> None:
    frame = _frame()
    pivots = _pivots(frame, [("high", 1, 2, 130), ("high", 4, 6, 120)])
    result = event_flags(frame, pivots, 3)
    assert _row(result, 1, "X8") is False
    assert _row(result, 2, "X8") is False
    assert _row(result, 3, "X8") is True
    assert _row(result, 4, "X8") is False
    first = result.attrs["first_lower_high"]
    assert first["state"] == "triggered" and first["first_trigger_offset"] == 3
    assert first["metadata"]["extreme_index"] == 4
    assert first["metadata"]["confirmation_index"] == 6
    assert first["metadata"]["extreme_date"] == cast(pd.Timestamp, frame.index[4]).date().isoformat()
    assert first["metadata"]["confirmed_at"] == cast(pd.Timestamp, frame.index[6]).date().isoformat()


def test_x8_high_equality_is_false_and_other_k_is_ignored() -> None:
    frame = _frame()
    pivots = _pivots(frame, [("high", 0, 1, 130), ("high", 3, 4, 130), ("high", 5, 6, 110)])
    pivots.loc[2, "k"] = 2.0
    result = event_flags(frame, pivots, 2)
    assert _row(result, 2, "X8") is False
    assert _row(result, 4, "X8") is False
    assert result.attrs["first_lower_high"]["state"] == "all_false"


def test_high_pivots_confirmed_together_follow_extreme_order() -> None:
    frame = _frame()
    pivots = _pivots(frame, [("high", 0, 1, 130), ("high", 5, 6, 120), ("high", 4, 6, 140)])
    result = event_flags(frame, pivots, 2)
    assert _row(result, 4, "X8") is True
    assert result.attrs["first_lower_high"]["metadata"]["extreme_index"] == 5
    assert result.attrs["first_lower_high"]["metadata"]["previous_price"] == 140
    pd.testing.assert_frame_equal(result, event_flags(frame, pivots.iloc[::-1], 2))
    with pytest.raises(ValueError, match="duplicate"):
        event_flags(frame, pd.concat([pivots, pivots.iloc[[0]]]), 2)


def test_missing_close_does_not_bridge_confirmed_high_comparison_or_claim_first() -> None:
    frame = _frame()
    frame.loc[frame.index[5], "Close"] = np.nan
    pivots = _pivots(frame, [("high", 1, 2, 130), ("high", 4, 6, 120), ("high", 7, 8, 110)])
    result = event_flags(frame, pivots, 3)
    assert result.loc[2].isna().all()
    assert _row(result, 3, "X8") is None
    assert _row(result, 5, "X8") is True
    assert result.attrs["first_lower_high"]["state"] == "unknown"
    assert result.attrs["first_lower_high"]["metadata"] is None
    assert result.attrs["first_observed_lower_high"]["confirmation_index"] == 8


def test_first_high_without_predecessor_is_unknown_and_no_pivot_day_is_false() -> None:
    frame = _frame()
    result = event_flags(frame, _pivots(frame, [("high", 2, 4, 120)]), 0)
    assert _row(result, 3, "X8") is False
    assert _row(result, 4, "X8") is None
    assert _row(result, 5, "X8") is False


@pytest.mark.parametrize("column", ["SMA20", "SMA60", "BBLower"])
def test_missing_indicator_only_affects_its_flag(column: str) -> None:
    frame = _frame()
    frame.loc[frame.index[1], column] = np.nan
    result = event_flags(frame, _pivots(frame, []), 0, support=105, lower=90)
    flag = {"SMA20": "X5_MA20", "SMA60": "X5_MA60", "BBLower": "X7"}[column]
    assert _row(result, 1, flag) is None
    assert _row(result, 1, "Y1") is True
    assert _row(result, 1, "Y2") is False


def test_invalid_anchor_only_makes_anchor_dependent_flags_unknown() -> None:
    frame = _frame()
    frame.loc[frame.index[0], "Close"] = np.nan
    result = event_flags(frame, _pivots(frame, []), 0, support=105)
    assert bool(result[["X6_10", "X6_15", "Y3"]].isna().to_numpy().all())
    assert _row(result, 1, "Y1") is True


def test_future_price_and_pivot_suffixes_do_not_change_earlier_daily_flags() -> None:
    frame = _frame()
    pivots = _pivots(frame, [("high", 1, 2, 130), ("high", 4, 6, 120), ("high", 8, 10, 110)])
    full = event_flags(frame, pivots, 3, support=95, lower=90)
    for cut in range(4, len(frame) + 1):
        prefix = event_flags(frame.iloc[:cut], pivots.loc[pivots["confirmation_index"] < cut], 3, support=95, lower=90)
        pd.testing.assert_frame_equal(prefix, full.iloc[: cut - 4])
    changed = frame.copy()
    changed.loc[changed.index[9:], "Close"] = 10
    pd.testing.assert_frame_equal(full.iloc[:5], event_flags(changed, pivots, 3, support=95, lower=90).iloc[:5])


def test_no_future_rows_is_valid_empty_result() -> None:
    frame = _frame(1)
    result = event_flags(frame, _pivots(frame, []), 0)
    assert result.empty and tuple(result.columns) == FLAG_IDS
    assert result.attrs["first_lower_high"]["state"] == "all_false"


@pytest.mark.parametrize(
    "field,value",
    [
        ("confirmation_index", 20),
        ("extreme_index", 5),
        ("price", 0),
        ("kind", "bad"),
        ("confirmed_at", pd.Timestamp("1999-01-01")),
        ("extreme_date", pd.Timestamp("1999-01-01")),
    ],
)
def test_malformed_pivot_calendar_rejected(field: str, value: object) -> None:
    frame = _frame()
    pivots = _pivots(frame, [("high", 1, 2, 130)])
    pivots[field] = value
    with pytest.raises(ValueError):
        event_flags(frame, pivots, 0)


def test_observations_use_full_horizons_and_four_landmark_clocks() -> None:
    frame = _frame(253)
    result = event_flag_observations(frame, _pivots(frame, []), 0)
    assert len(result) == 90
    assert set(result["horizon"]) == {126, 252}
    assert set(result.loc[result["scope"] == "landmark", "landmark"]) == {5, 10, 20, 40}
    assert bool(cast(pd.Series, result["calendar_full"]).all())
    assert set(result["riskset_id"]) == {"new_no_hit_valid_prefix"}


def test_landmark_hit_on_same_day_excludes_flag_but_raw_clock_keeps_it() -> None:
    frame = _frame(6)
    frame.loc[frame.index[2], "Close"] = 200
    frame.loc[frame.index[2], "SMA20"] = 210
    result = event_flag_observations(frame, _pivots(frame, []), 0, support=90, horizons=(5,), landmarks=(2,))
    row = result.loc[(result["flag_id"] == "X5_MA20") & (result["landmark"] == 2)].iloc[0]
    assert row["flag_state"] == "all_false"
    assert row["through_offset"] == 1
    assert row["raw_flag_state"] == "triggered"
    assert row["raw_first_trigger_offset"] == 2
    assert row["riskset_state"] == "early_hit" and not row["riskset_eligible"]


def test_first_decision_unknown_absorbs_later_true_but_true_absorbs_later_unknown() -> None:
    frame = _frame(6)
    frame.loc[frame.index[1], "SMA20"] = np.nan
    frame.loc[frame.index[2], "SMA20"] = 110
    first = event_flag_observations(frame, _pivots(frame, []), 0, horizons=(5,), landmarks=())
    row = first.loc[first["flag_id"] == "X5_MA20"].iloc[0]
    assert row["flag_state"] == "unknown" and row["unknown_reason"] == "missing_before_trigger"
    frame.loc[frame.index[1], "SMA20"] = 110
    frame.loc[frame.index[2], "SMA20"] = np.nan
    second = event_flag_observations(frame, _pivots(frame, []), 0, horizons=(5,), landmarks=())
    row = second.loc[second["flag_id"] == "X5_MA20"].iloc[0]
    assert row["flag_state"] == "triggered" and row["first_trigger_offset"] == 1


def test_support_break_does_not_remove_new_landmark_riskset() -> None:
    frame = _frame(6)
    frame.loc[frame.index[1], "Close"] = 70
    result = event_flag_observations(frame, _pivots(frame, []), 0, support=80, horizons=(5,), landmarks=(2,))
    row = result.loc[(result["flag_id"] == "Y1") & (result["landmark"] == 2)].iloc[0]
    assert row["riskset_eligible"]
    assert row["flag_state"] == "triggered" and row["trigger_return"] == pytest.approx(-0.3)


def test_truncated_future_retains_unknown_horizon_and_flag_clock() -> None:
    frame = _frame(3)
    result = event_flag_observations(frame, _pivots(frame, []), 0, horizons=(126,), landmarks=())
    row = result.loc[result["flag_id"] == "X6_10"].iloc[0]
    assert not row["calendar_full"] and row["label"] == "unknown"
    assert row["flag_state"] == "unknown" and row["unknown_reason"] == "window_end"


def test_observation_wrapper_bounds_prices_and_pivots_without_rebasing(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _frame(300)
    pivots = _pivots(frame, [("high", 1, 2, 130), ("high", 10, 20, 120), ("high", 280, 290, 110)])
    calls: list[tuple[int, list[int], int]] = []
    original = event_flags

    def spy(bounded: pd.DataFrame, bounded_pivots: pd.DataFrame, t0: int, **kwargs: float | None) -> pd.DataFrame:
        calls.append((len(bounded), bounded_pivots["confirmation_index"].tolist(), t0))
        assert bounded.index[0] == frame.index[0]
        return original(bounded, bounded_pivots, t0, **kwargs)

    monkeypatch.setattr(flag_module, "event_flags", spy)
    result = event_flag_observations(frame, pivots, 5)
    assert calls == [(258, [2, 20], 5)]
    assert bool(cast(pd.Series, result["calendar_full"]).all())


def test_late_prices_and_confirmations_beyond_max_horizon_do_not_change_observations() -> None:
    frame = _frame(20)
    pivots = _pivots(frame, [("high", 0, 1, 130), ("high", 3, 4, 120), ("high", 10, 15, 110)])
    baseline = event_flag_observations(frame, pivots, 2, horizons=(5,), landmarks=(2,))
    changed = frame.copy()
    changed.loc[changed.index[8:], ["Close", "SMA20", "SMA60", "BBLower"]] = np.nan
    changed_pivots = pivots.copy()
    changed_pivots.loc[2, "price"] = 1000
    actual = event_flag_observations(changed, changed_pivots, 2, horizons=(5,), landmarks=(2,))
    pd.testing.assert_frame_equal(actual, baseline)


def test_new_riskset_has_no_missing_fixed_support_restriction() -> None:
    frame = _frame(6)
    result = event_flag_observations(frame, _pivots(frame, []), 0, support=None, lower=None, horizons=(5,), landmarks=(2,))
    assert bool(cast(pd.Series, result["riskset_eligible"]).all())
    assert set(result.loc[result["flag_id"].isin(["Y1", "Y2", "Y3"]), "flag_state"]) == {"unknown"}

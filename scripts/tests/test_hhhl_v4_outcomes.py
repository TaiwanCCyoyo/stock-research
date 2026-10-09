"""Synthetic-only regressions for HHHL v4 outcomes and fixed landmarks."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_probability import OUTCOME_COLUMNS
from research_core.hhhl_v4_outcomes import first_decision_outcomes, landmark_record


def _valid(value: float) -> bool:
    return np.isfinite(value) and value > 0


def _naive_outcome(values: np.ndarray, anchor: int, horizon: int, target: float) -> dict[str, object]:
    anchor_close = values[anchor]
    anchor_valid = _valid(anchor_close)
    stop = min(anchor + horizon + 1, len(values))
    future = values[anchor + 1 : stop]
    observed = sum(_valid(value) for value in future)
    complete = anchor_valid and len(future) == horizon and all(_valid(value) for value in future)
    expected: dict[str, object] = {
        f"label_{horizon}": np.nan,
        f"complete_{horizon}": complete,
        f"unknown_reason_{horizon}": None,
        f"max_return_{horizon}": np.nan,
        f"min_return_{horizon}": np.nan,
        f"max_drawdown_{horizon}": np.nan,
        f"forward_return_{horizon}": np.nan,
        f"wait_to_threshold_{horizon}": np.nan,
        f"observed_sessions_{horizon}": observed,
    }
    if not anchor_valid:
        expected[f"unknown_reason_{horizon}"] = "invalid_anchor"
        return expected

    for offset, value in enumerate(future, start=1):
        if not _valid(value):
            expected[f"unknown_reason_{horizon}"] = "missing_before_hit"
            break
        if value / anchor_close >= target:
            expected[f"label_{horizon}"] = 1.0
            expected[f"wait_to_threshold_{horizon}"] = offset
            break
    else:
        if len(future) < horizon:
            expected[f"unknown_reason_{horizon}"] = "window_end"
        else:
            expected[f"label_{horizon}"] = 0.0

    if complete:
        path = values[anchor : anchor + horizon + 1]
        relative = path / anchor_close
        expected[f"max_return_{horizon}"] = relative[1:].max() - 1.0
        expected[f"min_return_{horizon}"] = relative[1:].min() - 1.0
        expected[f"max_drawdown_{horizon}"] = np.max(1.0 - path / np.maximum.accumulate(path))
        expected[f"forward_return_{horizon}"] = relative[-1] - 1.0
    return expected


def _assert_same_value(actual: Any, expected: Any) -> None:
    if isinstance(expected, (float, np.floating)) and np.isnan(expected):
        assert pd.isna(actual)
    elif isinstance(expected, (float, np.floating, int, np.integer)) and not isinstance(expected, (bool, np.bool_)):
        assert float(actual) == pytest.approx(float(expected))
    else:
        assert actual == expected


def test_first_decision_schema_and_exact_horizon_hits_are_inclusive() -> None:
    close = np.full(127, 100.0)
    close[63] = 150.0
    close[126] = 200.0

    result = first_decision_outcomes(close)

    assert result.index.equals(pd.RangeIndex(127))
    assert list(result.columns) == [*OUTCOME_COLUMNS, "observed_sessions_63", "observed_sessions_126"]
    assert result.loc[0, "label_63"] == 1
    assert result.loc[0, "wait_to_threshold_63"] == 63
    assert result.loc[0, "label_126"] == 1
    assert result.loc[0, "wait_to_threshold_126"] == 126
    assert result.loc[0, "complete_126"]
    assert result.loc[0, "observed_sessions_126"] == 126


def test_missing_before_later_hit_is_unknown_but_hit_before_missing_is_absorbing() -> None:
    missing_first = np.full(127, 100.0)
    missing_first[2] = np.nan
    missing_first[3] = 200.0
    unknown = first_decision_outcomes(missing_first).iloc[0]
    assert pd.isna(unknown["label_126"])
    assert unknown["unknown_reason_126"] == "missing_before_hit"
    assert not unknown["complete_126"]
    assert unknown["observed_sessions_126"] == 125

    hit_first = np.full(127, 100.0)
    hit_first[1] = 200.0
    hit_first[2] = np.nan
    known = first_decision_outcomes(hit_first).iloc[0]
    assert known["label_126"] == 1
    assert known["wait_to_threshold_126"] == 1
    assert known["unknown_reason_126"] is None
    assert not known["complete_126"]
    for metric in ("max_return", "min_return", "max_drawdown", "forward_return"):
        assert pd.isna(known[f"{metric}_126"])


def test_truncation_keeps_an_earlier_hit_known_and_unknown_without_hit() -> None:
    hit = np.full(9, 100.0)
    hit[1] = 200.0
    known = first_decision_outcomes(hit).iloc[0]
    assert known["label_126"] == 1
    assert known["wait_to_threshold_126"] == 1
    assert known["unknown_reason_126"] is None
    assert not known["complete_126"]
    assert pd.isna(known["min_return_126"])

    no_hit = first_decision_outcomes(np.full(9, 100.0)).iloc[0]
    assert pd.isna(no_hit["label_126"])
    assert no_hit["unknown_reason_126"] == "window_end"
    assert no_hit["observed_sessions_126"] == 8

    missing_then_truncated = np.full(9, 100.0)
    missing_then_truncated[3] = np.inf
    row = first_decision_outcomes(missing_then_truncated).iloc[0]
    assert row["unknown_reason_126"] == "missing_before_hit"


@pytest.mark.parametrize("invalid", [np.nan, np.inf, 0.0, -1.0])
def test_invalid_anchor_has_its_own_unknown_reason(invalid: float) -> None:
    close = np.full(127, 100.0)
    close[0] = invalid
    row = first_decision_outcomes(close).iloc[0]
    assert pd.isna(row["label_126"])
    assert row["unknown_reason_126"] == "invalid_anchor"
    assert not row["complete_126"]


def test_complete_path_extrema_and_drawdown_include_anchor_and_future_peak() -> None:
    close = np.full(127, 100.0)
    close[1] = 120.0
    close[2] = 60.0
    close[126] = 90.0

    row = first_decision_outcomes(close).iloc[0]

    assert row["label_126"] == 0
    assert row["max_return_126"] == pytest.approx(0.2)
    assert row["min_return_126"] == pytest.approx(-0.4)
    assert row["max_drawdown_126"] == pytest.approx(0.5)
    assert row["forward_return_126"] == pytest.approx(-0.1)


def test_outcome_array_matches_naive_first_decision_over_randomized_paths() -> None:
    rng = np.random.default_rng(20261010)
    close = rng.lognormal(mean=np.log(100.0), sigma=0.3, size=181)
    close[rng.choice(len(close), size=19, replace=False)] = rng.choice([np.nan, np.inf, 0.0, -2.0], size=19)

    actual = first_decision_outcomes(close)

    for anchor in range(len(close)):
        for horizon, target in ((63, 1.5), (126, 2.0)):
            expected = _naive_outcome(close, anchor, horizon, target)
            for column, value in expected.items():
                _assert_same_value(actual.iloc[anchor][column], value)


def test_landmark_uses_strict_bonus_crosses_and_fixed_rise_bins() -> None:
    close = np.full(127, 100.0)
    close[1:4] = [110.0, 120.0, 125.0]
    result = landmark_record(
        close,
        anchor=0,
        landmark=3,
        z2=90.0,
        bonus_levels=[{"age": "old", "level": 110.0}, {"age": "recent_far", "level": 120.0}],
    )
    assert result["status"] == "active"
    assert result["rise_ratio"] == pytest.approx(1.25)
    assert result["rise_bin"] == "ge1p25"
    assert result["cross_old"] is True
    assert result["cross_recent_far"] is True
    assert result["first_cross_old_index"] == 2  # Equality at index 1 is not a cross.
    assert result["first_cross_recent_far_index"] == 3
    assert result["group"] == "cross_both"


@pytest.mark.parametrize(
    ("endpoint", "expected_bin"),
    [(99.0, "lt1"), (100.0, "b1_1p10"), (110.0, "b1p10_1p25"), (125.0, "ge1p25")],
)
def test_landmark_rise_bin_boundaries(endpoint: float, expected_bin: str) -> None:
    close = np.full(127, 100.0)
    close[1] = endpoint
    row = landmark_record(close, 0, 1, 90.0, [])
    assert row["status"] == "active"
    assert row["rise_bin"] == expected_bin
    assert row["group"] == "clean_reference"
    assert row["cross_old"] is False and row["cross_recent_far"] is False


@pytest.mark.parametrize(
    ("path", "levels", "expected_group"),
    [
        (
            [111.0, 105.0],
            [{"age": "old", "level": 110.0}, {"age": "recent_far", "level": 120.0}],
            "cross_old_only",
        ),
        (
            [105.0, 121.0],
            [{"age": "old", "level": 130.0}, {"age": "recent_far", "level": 120.0}],
            "cross_recent_far_only",
        ),
        (
            [131.0, 141.0],
            [{"age": "old", "level": 130.0}, {"age": "recent_far", "level": 140.0}],
            "cross_both",
        ),
        (
            [105.0, 110.0],
            [{"age": "old", "level": 115.0}, {"age": "recent_far", "level": 125.0}],
            "uncrossed_overhead",
        ),
    ],
)
def test_landmark_bonus_groups(path: list[float], levels: list[dict[str, Any]], expected_group: str) -> None:
    close = np.full(127, 100.0)
    close[1:3] = path
    row = landmark_record(close, 0, 2, 90.0, levels)
    assert row["status"] == "active"
    assert row["group"] == expected_group


def test_landmark_target_equality_and_early_status_absorbs_later_missing() -> None:
    close = np.full(30, 100.0)
    close[2] = 200.0
    close[4] = np.nan
    row = landmark_record(close, 0, 4, 90.0, [])
    assert row["status"] == "early_hit"
    assert row["reason"] is None
    assert row["landmark_index"] == 4
    assert row["label_126"] is None
    assert all(row[column] is None for column in OUTCOME_COLUMNS if column.endswith("_126"))


def test_landmark_failure_is_strict_and_absorbs_later_missing() -> None:
    equal = np.full(127, 100.0)
    equal[1] = 90.0
    assert landmark_record(equal, 0, 2, 90.0, [])["status"] == "active"

    failed = np.full(8, 100.0)
    failed[1] = np.nextafter(90.0, 0.0)
    failed[3] = np.nan
    row = landmark_record(failed, 0, 5, 90.0, [])
    assert row["status"] == "early_failed"
    assert row["reason"] is None
    assert row["label_126"] is None


def test_landmark_missing_before_later_hit_and_truncation_remain_unknown() -> None:
    missing_first = np.full(127, 100.0)
    missing_first[1] = np.nan
    missing_first[2] = 200.0
    row = landmark_record(missing_first, 0, 4, 90.0, [])
    assert row["status"] == "unknown"
    assert row["reason"] == "missing_before_landmark"
    assert row["rise_ratio"] is None

    truncated = landmark_record(np.full(3, 100.0), 0, 3, 90.0, [])
    assert truncated["status"] == "unknown"
    assert truncated["reason"] == "window_end"

    truncated_after_hit = np.array([100.0, 200.0, 100.0])
    absorbed = landmark_record(truncated_after_hit, 0, 4, 90.0, [])
    assert absorbed["status"] == "early_hit"
    assert absorbed["reason"] is None


def test_landmark_active_remainder_keeps_original_deadline_and_ignores_later_z2_failure() -> None:
    close = np.full(127, 100.0)
    close[20] = 120.0
    close[21] = 80.0  # A post-landmark fall below z2 does not change active status.
    close[126] = 200.0

    row = landmark_record(close, 0, 20, 90.0, [])

    assert row["status"] == "active"
    assert row["label_126"] == 1
    assert row["wait_to_threshold_126"] == 126
    assert row["wait_from_landmark"] == 106
    assert row["complete_126"] is True
    assert row["min_return_126"] == pytest.approx(-0.2)
    assert row["max_drawdown_126"] == pytest.approx(1.0 - 80.0 / 120.0)

    beyond_original_deadline = np.full(147, 100.0)
    beyond_original_deadline[146] = 200.0
    no_reset = landmark_record(beyond_original_deadline, 0, 20, 90.0, [])
    assert no_reset["status"] == "active"
    assert no_reset["label_126"] == 0
    assert no_reset["wait_to_threshold_126"] is None


def test_landmark_remainder_metrics_exclude_pre_landmark_dips() -> None:
    close = np.full(127, 100.0)
    close[3] = 80.0
    close[20] = 100.0

    row = landmark_record(close, 0, 20, 70.0, [])

    assert row["status"] == "active"
    assert row["label_126"] == 0
    assert row["min_return_126"] == pytest.approx(0.0)
    assert row["max_return_126"] == pytest.approx(0.0)
    assert row["max_drawdown_126"] == pytest.approx(0.0)


def test_active_remainder_missing_before_hit_keeps_metrics_null() -> None:
    close = np.full(127, 100.0)
    close[20] = 110.0
    close[30] = np.nan
    close[40] = 200.0
    row = landmark_record(close, 0, 20, 90.0, [])
    assert row["status"] == "active"
    assert row["label_126"] is None
    assert row["unknown_reason_126"] == "missing_before_hit"
    assert row["complete_126"] is False
    assert row["min_return_126"] is None
    assert row["max_drawdown_126"] is None


@pytest.mark.parametrize("invalid", [np.nan, np.inf, 0.0, -1.0])
def test_landmark_invalid_anchor_is_unknown(invalid: float) -> None:
    close = np.full(127, 100.0)
    close[3] = invalid
    row = landmark_record(close, 3, 2, 90.0, [])
    assert row["status"] == "unknown"
    assert row["reason"] == "invalid_anchor"
    assert row["label_126"] is None


def test_outcome_close_input_requires_one_dimensional_float_coercible_values() -> None:
    with pytest.raises(ValueError, match="one-dimensional"):
        first_decision_outcomes(np.ones((2, 2)))
    with pytest.raises(ValueError, match="float-coercible"):
        first_decision_outcomes(np.array(["100", "not-a-price"], dtype=object))
    coerced = first_decision_outcomes(np.array(["100", "150", *(["100"] * 125)], dtype=object))
    assert coerced.loc[0, "label_63"] == 1


def test_empty_close_returns_empty_range_index_with_fixed_schema() -> None:
    result = first_decision_outcomes(np.array([], dtype=float))
    assert result.empty
    assert result.index.equals(pd.RangeIndex(0))
    assert list(result.columns) == [*OUTCOME_COLUMNS, "observed_sessions_63", "observed_sessions_126"]

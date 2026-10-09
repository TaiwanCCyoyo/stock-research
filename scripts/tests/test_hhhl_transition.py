"""Hand-checkable synthetic transition paths; no market or outcome data."""

import numpy as np
import pytest

from research_core.hhhl_transition import classify_transition


def test_failure_is_terminal_before_low_confirmation() -> None:
    result = classify_transition(np.array([10.0, 8.0, 12.0, 13.0]), 0, 9.0, [(1, 2, 7.0)])
    assert (result.status, result.anchor_index) == ("failed", 1)
    assert result.first_low_index is None
    assert not result.confirmation_day_excluded


def test_first_low_threshold_stays_fixed_after_second_low() -> None:
    result = classify_transition(np.array([10.0, 12.0, 11.0, 13.0, 11.0, 11.5, 12.5]), 0, 9.0, [(2, 3, 10.0), (4, 5, 10.0)])
    assert (result.status, result.anchor_index) == ("stood", 6)
    assert (result.first_low_index, result.first_low_confirm_index, result.threshold) == (2, 3, 12.0)
    assert result.confirmation_day_excluded


@pytest.mark.parametrize("following, status, anchor", [(14.0, "stood", 3), (10.0, "unresolved", None)])
def test_confirmation_day_is_excluded(following: float, status: str, anchor: int | None) -> None:
    result = classify_transition(np.array([10.0, 9.5, 13.0, following]), 0, 9.0, [(1, 2, 9.0)], horizon=3)
    assert (result.status, result.anchor_index) == (status, anchor)
    assert result.confirmation_day_excluded
    assert result.threshold == 10.0


@pytest.mark.parametrize("values, lows", [([10.0, 9.5, 10.0, 10.0], [(1, 2, 9.0)]), ([10.0, 11.0, 12.0, 13.0], [])])
def test_equality_and_monotonic_rise_without_low_never_stand(values: list[float], lows: list[tuple[int, int, float]]) -> None:
    result = classify_transition(np.array(values), 0, 9.0, lows, horizon=3)
    assert (result.status, result.anchor_index) == ("unresolved", None)


@pytest.mark.parametrize("missing", [np.nan, np.inf, -np.inf])
def test_missing_common_calendar_close_stops_before_later_stand(missing: float) -> None:
    result = classify_transition(np.array([10.0, 9.5, 10.0, missing, 14.0]), 0, 9.0, [(1, 2, 9.0)], horizon=4)
    assert (result.status, result.anchor_index) == ("unknown_missing_close", None)
    assert (result.first_low_index, result.first_low_confirm_index, result.threshold) == (1, 2, 10.0)


def test_pre_breakout_extreme_confirmed_later_is_ignored() -> None:
    result = classify_transition(np.array([9.0, 10.0, 11.0, 10.5, 11.0, 12.0]), 1, 9.0, [(0, 2, 8.0), (3, 4, 10.0)])
    assert (result.status, result.anchor_index) == ("stood", 5)
    assert (result.first_low_index, result.first_low_confirm_index, result.threshold) == (3, 4, 11.0)


def test_truncated_end_retains_first_low_and_has_no_anchor() -> None:
    result = classify_transition(np.array([10.0, 9.5, 10.0, 10.0]), 0, 9.0, [(1, 2, 9.0)])
    assert (result.status, result.anchor_index) == ("unknown_window_end", None)
    assert (result.first_low_index, result.first_low_confirm_index, result.threshold) == (1, 2, 10.0)


@pytest.mark.parametrize("future_days, status", [(125, "unknown_window_end"), (126, "unresolved")])
def test_default_window_requires_126_common_calendar_days(future_days: int, status: str) -> None:
    result = classify_transition(np.full(future_days + 1, 10.0), 0, 10.0, [])
    assert (result.status, result.anchor_index) == (status, None)


@pytest.mark.parametrize("value, status, anchor", [(8.0, "failed", 2), (np.nan, "unknown_missing_close", None)])
def test_failure_or_missing_on_confirmation_day_precedes_low(value: float, status: str, anchor: int | None) -> None:
    result = classify_transition(np.array([10.0, 9.5, value, 14.0]), 0, 9.0, [(1, 2, 9.0)])
    assert (result.status, result.anchor_index) == (status, anchor)
    assert result.first_low_index is None
    assert not result.confirmation_day_excluded


@pytest.mark.parametrize(
    "breakout, zone, lows",
    [(-1, 9.0, []), (4, 9.0, []), (0, np.nan, []), (0, 9.0, [(1, 4, 9.0)]), (0, 9.0, [(2, 1, 9.0)]), (0, 9.0, [(1, 3, 9.0), (0, 2, 9.0)])],
)
def test_invalid_indices_zone_and_pivot_mappings_fail_clearly(breakout: int, zone: float, lows: list[tuple[int, int, float]]) -> None:
    with pytest.raises(ValueError):
        classify_transition(np.array([10.0, 10.0, 10.0, 10.0]), breakout, zone, lows)

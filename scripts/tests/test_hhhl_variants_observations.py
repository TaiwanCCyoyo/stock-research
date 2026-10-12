"""Synthetic-only calendar and timing regressions; no market inputs."""

from datetime import date, timedelta

import pytest

from research_core.hhhl_variants_observations import (
    classify_window,
    confirmed_pivot_view,
    flag_history,
    landmark_riskset,
    previous_completed_week_signal,
)


@pytest.mark.parametrize("invalid", [None, float("nan"), float("inf"), 0.0, -1.0])
def test_invalid_anchor_remains_unknown(invalid: float | None) -> None:
    result = classify_window([invalid, 200.0, 100.0], 2)
    assert result.outcome == "unknown"
    assert result.reason == "invalid_anchor"
    assert result.calendar_full and not result.full_path and not result.main_eligible
    assert result.first_missing_offset == 0


def test_missing_before_hit_cannot_be_skipped() -> None:
    result = classify_window([100.0, None, 200.0], 2)
    assert result.outcome == "unknown"
    assert result.first_hit_offset is None
    assert result.first_missing_offset == 1
    assert result.reason == "missing_before_hit"


def test_hit_absorbs_missing_but_censoring_stays_outside_main() -> None:
    full = classify_window([100.0, 200.0, None], 2)
    censored = classify_window([100.0, 200.0, None], 3)
    assert full.outcome == censored.outcome == "hit"
    assert full.first_hit_offset == censored.first_hit_offset == 1
    assert full.reason is censored.reason is None
    assert full.first_missing_offset == censored.first_missing_offset == 2
    assert full.calendar_full and full.main_eligible and not full.full_path
    assert not censored.calendar_full and not censored.main_eligible and not censored.full_path


@pytest.mark.parametrize("endpoint,outcome", [(200.0, "hit"), (100.0, "flat-win"), (99.0, "loss"), (199.0, "flat-win")])
def test_inclusive_target_and_strict_loss(endpoint: float, outcome: str) -> None:
    result = classify_window([100.0, 110.0, endpoint], 2)
    assert result.outcome == outcome
    assert result.full_path and result.main_eligible
    assert result.first_hit_offset == (2 if outcome == "hit" else None)


@pytest.mark.parametrize("horizon", [126, 252])
def test_fixed_horizons_and_unobserved_end(horizon: int) -> None:
    assert classify_window([100.0] * (horizon + 1), horizon).outcome == "flat-win"
    result = classify_window([100.0] * horizon, horizon)
    assert result.outcome == "unknown" and result.reason == "window_end"


def test_new_support_break_stays_in_while_legacy_absorbs_failure() -> None:
    closes = [100.0, 70.0, 110.0]
    new = landmark_riskset(closes, 2, 80.0)
    legacy = landmark_riskset(closes, 2, 80.0, legacy_active=True)
    assert new.eligible and new.state == "active"
    assert legacy.state == "early_failed" and legacy.decision_offset == 1
    assert not legacy.eligible and new.riskset_id != legacy.riskset_id


@pytest.mark.parametrize("legacy", [False, True])
def test_landmark_endpoint_missing_and_hit_count(legacy: bool) -> None:
    missing = landmark_riskset([100.0, 120.0, None], 2, 80.0, legacy_active=legacy)
    hit = landmark_riskset([100.0, 120.0, 200.0], 2, 80.0, legacy_active=legacy)
    assert missing.state == "early_unknown" and missing.decision_offset == 2
    assert hit.state == "early_hit" and hit.decision_offset == 2


def test_new_requires_full_prefix_while_legacy_first_event_absorbs() -> None:
    assert landmark_riskset([100.0, 200.0, None], 2, 80.0).state == "early_unknown"
    assert landmark_riskset([100.0, 200.0, None], 2, 80.0, legacy_active=True).state == "early_hit"
    assert landmark_riskset([100.0, None, 70.0], 2, 80.0, legacy_active=True).state == "early_unknown"
    assert landmark_riskset([100.0, 70.0, 200.0], 2, 80.0, legacy_active=True).state == "early_failed"
    assert landmark_riskset([100.0, 200.0], 2, 80.0).reason == "window_end"
    assert landmark_riskset([100.0, 200.0], 2, 80.0, legacy_active=True).state == "early_hit"


def test_landmark_support_equality_and_invalid_anchor() -> None:
    assert landmark_riskset([100.0, 80.0], 1, 80.0, legacy_active=True).eligible
    assert landmark_riskset([None, 100.0], 1, 80.0).reason == "invalid_anchor"


def test_trigger_at_landmark_counts_but_same_day_hit_does_not() -> None:
    flags = [True, False, True]
    at_l = flag_history(flags, 2, first_hit_offset=3)
    assert at_l.state == "triggered" and at_l.first_trigger_offset == 2
    same_day = flag_history(flags, 2, first_hit_offset=2)
    assert same_day.state == "all_false" and same_day.through_offset == 1
    assert flag_history([True], 1, first_hit_offset=1).state == "all_false"


def test_flag_unknown_before_true_is_absorbing_but_after_true_is_not() -> None:
    unknown = flag_history([False, None, True], 2)
    assert unknown.state == "unknown" and unknown.first_trigger_offset is None
    assert unknown.reason == "missing_before_trigger"
    known = flag_history([None, True, None], 2)
    assert known.state == "triggered" and known.first_trigger_offset == 1
    assert flag_history([True, False], 2).reason == "window_end"
    assert flag_history([None, False, False], 2).state == "all_false"


def _weeks(count: int = 13) -> tuple[list[date], list[float | None]]:
    start = date(2026, 1, 5)  # Monday, with a complete first represented week.
    dates = [start + timedelta(days=7 * week + day) for week in range(count) for day in range(5)]
    closes: list[float | None] = [float(100 + week) for week in range(count) for _ in range(5)]
    return dates, closes


def test_friday_excludes_entire_t0_week_and_future_prices() -> None:
    dates, closes = _weeks()
    friday = 11 * 5 + 4
    assert previous_completed_week_signal(dates, closes, friday) is True
    changed = closes.copy()
    changed[11 * 5 :] = [None] * (len(changed) - 11 * 5)
    assert previous_completed_week_signal(dates, changed, friday) is True
    assert previous_completed_week_signal(dates, changed, 11 * 5) is True


def test_week_signal_strict_equality_and_eleven_completed_weeks() -> None:
    dates, closes = _weeks()
    assert previous_completed_week_signal(dates, closes, 10 * 5 + 4) is None
    assert previous_completed_week_signal(dates, [100.0] * len(closes), 11 * 5) is False
    assert previous_completed_week_signal(dates, list(reversed(closes)), 11 * 5) is False


def test_any_missing_daily_close_invalidates_week_and_requires_new_warmup() -> None:
    dates, closes = _weeks(24)
    closes[5 * 5 + 1] = None  # The final close is valid; the week still is not.
    assert previous_completed_week_signal(dates, closes, 16 * 5) is None
    assert previous_completed_week_signal(dates, closes, 17 * 5) is True


def test_first_partial_week_is_not_warmup_and_no_trade_week_is_not_invented() -> None:
    dates, closes = _weeks()
    assert previous_completed_week_signal(dates[1:], closes[1:], 11 * 5 - 1) is None
    assert previous_completed_week_signal(dates[1:], closes[1:], 12 * 5 - 1) is True
    # Skip one whole synthetic holiday week: eleven observed weeks still suffice.
    dates, closes = _weeks(14)
    holiday_dates = dates[:25] + dates[30:]
    holiday_closes = closes[:25] + closes[30:]
    assert previous_completed_week_signal(holiday_dates, holiday_closes, 11 * 5) is True


def test_pivot_view_uses_confirmation_not_extreme_date() -> None:
    dates, _ = _weeks(1)
    pivots = [(0, 2, 100.0), (1, 4, 110.0)]
    assert confirmed_pivot_view(pivots, dates, dates[1]) == ()
    view = confirmed_pivot_view(pivots, dates, dates[2])
    assert len(view) == 1
    assert view[0].extreme_date == dates[0] and view[0].confirmed_at == dates[2]
    assert view[0].extreme_index == 0 and view[0].confirmed_index == 2


@pytest.mark.parametrize("indexes", [(-1, 2), (3, 2), (0, 5), (True, 2)])
def test_invalid_pivot_indexes_rejected_even_if_unconfirmed(indexes: tuple[int, int]) -> None:
    dates, _ = _weeks(1)
    with pytest.raises(ValueError):
        confirmed_pivot_view([(*indexes, 100.0)], dates, dates[0])


@pytest.mark.parametrize("bad", [0, -1, True, 1.5])
def test_positive_offsets_rejected(bad: int) -> None:
    with pytest.raises(ValueError):
        classify_window([100.0], bad)
    with pytest.raises(ValueError):
        landmark_riskset([100.0], bad, 80.0)


def test_malformed_flag_calendar_support_and_pivot_inputs() -> None:
    dates, closes = _weeks(1)
    with pytest.raises(ValueError):
        flag_history([False, 1], 1)  # type: ignore[list-item]
    with pytest.raises(ValueError):
        landmark_riskset([100.0], 1, float("nan"))
    with pytest.raises(ValueError):
        previous_completed_week_signal(dates, closes[:-1], 0)
    with pytest.raises(ValueError):
        previous_completed_week_signal(list(reversed(dates)), closes, 0)
    with pytest.raises(ValueError):
        confirmed_pivot_view([(0, 2, 0.0)], dates, dates[4])

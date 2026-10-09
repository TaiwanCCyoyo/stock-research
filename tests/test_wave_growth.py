from __future__ import annotations

import math

import pytest

from research_core.wave_growth import YEAR_DAYS, classify_growth, wave_gain


def test_long_wave_annualizes_known_total_gain():
    metric = wave_gain("2012-11-12", "2021-04-29", 1290)
    assert metric["totalGainPct"] == 1290
    assert metric["annualizedGainPct"] == pytest.approx(36.492499967, abs=1e-8)
    assert metric["sizingGainPct"] == metric["annualizedGainPct"]
    assert metric["basis"] == "annualized"
    assert metric["yearDays"] == YEAR_DAYS
    assert metric["reason"] is None


def test_short_and_long_threshold_classification_uses_shared_sizing_gain():
    one_day_10pct = wave_gain("2020-01-01", "2020-01-02", 10)
    short_100pct = wave_gain("2020-01-01", "2020-06-01", 100)
    two_year_300pct = wave_gain("2020-01-01", "2022-01-01", 300)
    assert one_day_10pct["annualizedGainPct"] is None
    assert one_day_10pct["sizingGainPct"] == 10
    assert classify_growth(one_day_10pct) == "below-threshold"
    assert classify_growth(short_100pct) == "eligible"
    assert two_year_300pct["elapsedDays"] == 731
    assert two_year_300pct["annualizedGainPct"] == pytest.approx(99.905, abs=0.01)
    assert classify_growth(two_year_300pct) == "below-threshold"


def test_inclusive_100_percent_threshold_tolerates_only_float_roundoff():
    four_years_1500 = wave_gain("2020-01-01", "2024-01-01", 1500)
    just_below = wave_gain("2020-01-01", "2020-01-02", 100 - 1e-7)
    assert four_years_1500["elapsedDays"] == 1461
    assert four_years_1500["sizingGainPct"] == pytest.approx(100, abs=1e-12)
    assert classify_growth(four_years_1500) == "eligible"
    assert classify_growth(just_below) == "below-threshold"


def test_365_days_is_actual_and_366_days_is_annualized():
    before_year = wave_gain("2020-01-01", "2020-12-31", 300)
    at_year = wave_gain("2020-01-01", "2021-01-01", 300)
    assert before_year["elapsedDays"] == 365
    assert before_year["basis"] == "actual"
    assert before_year["annualizedGainPct"] is None
    assert before_year["sizingGainPct"] == 300
    assert at_year["elapsedDays"] == 366
    assert at_year["basis"] == "annualized"
    annualized_gain = at_year["annualizedGainPct"]
    actual_gain = before_year["sizingGainPct"]
    assert annualized_gain is not None
    assert actual_gain is not None
    assert annualized_gain == pytest.approx(298.86530561096436)
    assert annualized_gain < actual_gain


@pytest.mark.parametrize("gain", [0, -10, -100])
def test_zero_and_negative_returns_remain_known_actual_returns(gain: float):
    metric = wave_gain("2020-01-01", "2020-01-02", gain)
    assert metric["totalGainPct"] == gain
    assert metric["sizingGainPct"] == gain
    assert metric["basis"] == "actual"
    assert classify_growth(metric) == "below-threshold"


@pytest.mark.parametrize("gain", [None, float("nan"), float("inf"), -100.01])
def test_missing_nonfinite_or_below_total_loss_is_unknown(gain: float | None):
    metric = wave_gain("2020-01-01", "2020-01-02", gain)
    assert metric["totalGainPct"] is None
    assert metric["basis"] == "unknown"
    assert metric["reason"] == "unknown-gain"
    assert classify_growth(metric) == "unknown"


@pytest.mark.parametrize(
    ("start", "observation"),
    [("2020-02-30", "2020-03-01"), ("2020-01-02", "2020-01-01"), ("bad", "2020-01-01")],
)
def test_invalid_or_reversed_interval_is_unknown(start: str, observation: str):
    metric = wave_gain(start, observation, 25)
    assert metric["totalGainPct"] == 25
    assert metric["elapsedDays"] is None
    assert metric["sizingGainPct"] is None
    assert metric["basis"] == "unknown"
    assert metric["reason"] == "invalid-interval"


def test_left_censored_start_preserves_total_but_leaves_adjusted_growth_unknown():
    metric = wave_gain("2020-01-01", "2022-01-01", 300, left_censored=True)
    assert metric["totalGainPct"] == 300
    assert metric["elapsedDays"] == 731
    assert metric["annualizedGainPct"] is None
    assert metric["sizingGainPct"] is None
    assert metric["basis"] == "unknown"
    assert metric["reason"] == "left-censored-start"
    assert classify_growth(metric) == "unknown"


def test_zero_day_interval_uses_actual_gain_and_threshold_must_be_positive_finite():
    metric = wave_gain("2020-01-01", "2020-01-01", 0)
    assert metric["elapsedDays"] == 0
    assert metric["basis"] == "actual"
    assert metric["sizingGainPct"] == 0
    for threshold in (0, -1, math.inf, float("nan"), True):
        with pytest.raises(ValueError, match="finite and positive"):
            classify_growth(metric, threshold)

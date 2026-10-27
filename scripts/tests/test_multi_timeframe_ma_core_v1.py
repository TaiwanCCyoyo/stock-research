"""Bounded, artificial cutoff fixtures only; no readers or market artifacts."""

from dataclasses import FrozenInstanceError, replace
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from research_core import derived_features, technical_daily_v1
from research_core.multi_timeframe_ma_core_v1 import (
    FALSE,
    PERIODS,
    TRUE,
    UNKNOWN,
    CutoffSeries,
    MovingAverages,
    bull_at_cutoff,
    density_at_cutoff,
    moving_averages,
    ratio_cross,
    weekly_turn,
)


def series_of(close: NDArray[np.float64], *, valid: NDArray[np.bool_] | None = None, weekly: bool = False) -> CutoffSeries:
    dates = pd.date_range("2020-01-01", periods=len(close), freq="7D" if weekly else "D")
    return CutoffSeries(
        "FAKE_A",
        "synthetic-G",
        cast(pd.Timestamp, dates[-1] if len(dates) else pd.Timestamp("2020-01-01")),
        "reference_factor_adjusted",
        "completed_weekly" if weekly else "daily",
        dates,
        close,
        np.ones(len(close), dtype=np.bool_) if valid is None else valid,
    )


@pytest.mark.parametrize("n", PERIODS)
@pytest.mark.parametrize("kind", ["constant", "rising", "falling"])
@pytest.mark.parametrize("weekly", [False, True])
def test_n_minus_one_seed_and_first_recurrence(n: int, kind: str, weekly: bool) -> None:
    close = np.full(n + 1, 10.0) if kind == "constant" else np.arange(1, n + 2, dtype=np.float64)
    if kind == "falling":
        close = close[::-1].copy()
    ma = moving_averages(series_of(close, weekly=weekly))
    seed = 10.0 if kind == "constant" else (float(close[0]) + float(close[n - 1])) / 2
    alpha = 2 / (n + 1)
    assert np.isnan(ma.sma[n][: n - 1]).all() and np.isnan(ma.ema[n][: n - 1]).all()
    assert ma.ema[n][n - 1] == seed and ma.sma[n][n - 1] == seed
    assert ma.ema[n][n] == alpha * close[n] + (1 - alpha) * seed
    assert ma.sma[n][n] == (float(close[1]) + float(close[n])) / 2
    assert ma.reasons[f"ema_warmup_{n}"][n - 2] and not ma.reasons[f"ema_warmup_{n}"][n - 1]
    assert ma.sma[n].dtype == ma.ema[n].dtype == np.dtype("float64")


@pytest.mark.parametrize("gap_kind", ["missing", "quality", "zero", "negative", "infinite", "none"])
def test_exact_public_oracle_parity_and_segment_resets(gap_kind: str) -> None:
    rng = np.random.Generator(np.random.PCG64(20261027))
    close = 100 + np.cumsum(rng.uniform(-0.3, 0.7, 302))
    valid = np.ones(len(close), dtype=np.bool_)
    if gap_kind == "quality":
        valid[150] = False
    elif gap_kind != "none":
        close[150] = {"missing": np.nan, "zero": 0.0, "negative": -1.0, "infinite": np.inf}[gap_kind]
    source = series_of(close, valid=valid)
    prepared = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": valid}, index=source.bar_dates)
    original = prepared.copy(deep=True)
    shared, _ = derived_features.compute_features(prepared)
    technical, _ = technical_daily_v1.compute_technical("FAKE_A", prepared)
    ma = moving_averages(source)
    for kind, periods in (("sma", PERIODS), ("ema", (20, 60))):
        averages = getattr(ma, kind)
        for n in periods:
            name = f"{kind.upper()}{n}"
            np.testing.assert_array_equal(averages[n], shared[name].to_numpy(), strict=True)
            np.testing.assert_array_equal(averages[n], technical[name].to_numpy(), strict=True)
    pd.testing.assert_frame_equal(prepared, original)
    if gap_kind != "none":
        for n in PERIODS:
            for output in (ma.sma[n], ma.ema[n]):
                assert len(output) == len(close)
                assert np.isnan(output[150 : 150 + n]).all()
                assert np.isfinite(output[150 + n])
        assert not ma.valid[150]
        assert ma.reasons["invalid_upstream" if gap_kind == "quality" else "invalid_close"][150]
        assert ma.ema[120][270] == float(pd.Series(close[151:271]).mean())


def test_ema_retains_seed_history_beyond_last_120_bars() -> None:
    close = np.full(300, 100.0)
    changed = close.copy()
    changed[:120] = 200.0
    original, revised = moving_averages(series_of(close)), moving_averages(series_of(changed))
    np.testing.assert_array_equal(close[-120:], changed[-120:])
    assert revised.sma[120][-1] == original.sma[120][-1]
    expected = 200.0
    alpha = 2 / 121
    for _ in range(180):
        expected = alpha * 100.0 + (1 - alpha) * expected
    assert revised.ema[120][-1] == expected > original.ema[120][-1]


@pytest.mark.parametrize("weekly", [False, True])
@pytest.mark.parametrize("factor", [0.25, 0.97, 2.0])
def test_full_history_same_cutoff_scaling_including_all_windows(weekly: bool, factor: float) -> None:
    # Artificial raw split/dividend jumps cross all three lookbacks. The caller
    # supplies one cutoff's consistent scale; this does not validate a reader.
    raw = np.arange(100, 360, dtype=np.float64)
    factors = np.ones(len(raw), dtype=np.float64)
    factors[:135] *= 0.5
    factors[:215] *= 0.97
    close = raw * factors
    source = series_of(close, weekly=weekly)
    scaled = series_of(close * factor, weekly=weekly)
    ma, other = moving_averages(source), moving_averages(scaled)
    for n in PERIODS:
        np.testing.assert_allclose(other.sma[n], ma.sma[n] * factor, rtol=2e-15, atol=0, equal_nan=True)
        np.testing.assert_allclose(other.ema[n], ma.ema[n] * factor, rtol=2e-15, atol=0, equal_nan=True)
    assert bull_at_cutoff(source, ma) == bull_at_cutoff(scaled, other)
    if weekly:
        assert density_at_cutoff(scaled, other).density == pytest.approx(density_at_cutoff(source, ma).density, rel=2e-14)


@pytest.mark.parametrize("weekly", [False, True])
def test_bull_strict_equalities_and_unknown_even_when_an_operand_is_false(weekly: bool) -> None:
    short = series_of(np.full(20, 10.0), weekly=weekly)
    short_state = bull_at_cutoff(short, moving_averages(short))
    assert short_state.state == UNKNOWN  # Close == SMA is false, lag20 is unknown.
    assert "lag20_close:insufficient_history" in short_state.reasons
    full = series_of(np.full(120, 10.0), weekly=weekly)
    assert bull_at_cutoff(full, moving_averages(full)).state == FALSE
    assert bull_at_cutoff(full, moving_averages(full)).strong_state == FALSE
    rising = series_of(np.r_[np.full(120, 10.0), 11.0], weekly=weekly)
    state = bull_at_cutoff(rising, moving_averages(rising))
    assert state.state == state.strong_state == TRUE and not state.reasons
    young = series_of(np.arange(1, 61, dtype=np.float64), weekly=weekly)
    state = bull_at_cutoff(young, moving_averages(young))
    assert state.state == TRUE and state.strong_state == UNKNOWN
    assert "sma120:sma_warmup_120" in state.strong_reasons


def test_lag20_uses_original_position_without_skipping_invalid_bars() -> None:
    close = np.arange(1, 181, dtype=np.float64)
    valid = np.ones(len(close), dtype=np.bool_)
    valid[-21] = False
    source = series_of(close, valid=valid)
    ma = moving_averages(source)
    assert np.isfinite(ma.sma[20][-1]) and np.isnan(ma.ema[20][-2])
    result = bull_at_cutoff(source, ma)
    assert result.state == UNKNOWN
    assert "lag20_close:invalid_upstream" in result.reasons
    assert "previous_ema20:ema_warmup_20" in result.reasons


def test_numeric_overflow_has_reasons_and_never_becomes_false_or_zero() -> None:
    source = series_of(np.full(121, 1e308), weekly=True)
    ma = moving_averages(source)
    assert ma.reasons["ema_nonfinite_120"][119]
    assert np.isnan(ma.ema[120][119:]).all()
    assert bull_at_cutoff(source, ma).state == UNKNOWN
    density = density_at_cutoff(source, ma)
    assert not density.known and density.density is None
    assert any("nonfinite" in reason for reason in density.reasons)
    # Finite, widely separated MAs can also overflow the std's squaring step.
    varied = series_of(np.r_[np.full(120, 1e160), np.full(120, 2e160)], weekly=True)
    result = density_at_cutoff(varied, moving_averages(varied))
    assert result.density is None and result.reasons == ("density_nonfinite",)


@pytest.mark.parametrize(("previous_true", "threshold", "cross_name"), [(9, 0.50, "cross50"), (13, 0.70, "cross70")])
def test_ratio_uses_fixed_20_and_crosses_only_from_below(previous_true: int, threshold: float, cross_name: str) -> None:
    states = np.array([FALSE] * (20 - previous_true) + [TRUE] * (previous_true + 2), dtype=np.int8)
    snapshot = states.copy()
    result = ratio_cross(states)
    assert np.isnan(result.ratio[:19]).all()
    assert result.ratio[19] == previous_true / 20
    assert result.ratio[20] == threshold and result.ratio[21] == (previous_true + 2) / 20
    cross = getattr(result, cross_name)
    assert cross[19] == UNKNOWN and cross[20] == TRUE and cross[21] == FALSE
    assert result.previous_ratio[20] == result.ratio[19]
    assert result.ratio.dtype == result.previous_ratio.dtype == np.dtype("float64")
    assert result.cross50.dtype == result.cross70.dtype == np.dtype("int8")
    np.testing.assert_array_equal(states, snapshot)


def test_unknown_ratio_window_and_previous_are_positional_not_last_known() -> None:
    states = np.full(43, TRUE, dtype=np.int8)
    states[21] = UNKNOWN
    result = ratio_cross(states)
    assert result.ratio[20] == 1.0
    assert np.isnan(result.ratio[21:41]).all()
    assert result.ratio[41] == 1.0 and np.isnan(result.previous_ratio[41])
    assert result.cross50[41] == result.cross70[41] == UNKNOWN
    assert result.cross50[42] == FALSE
    assert result.reasons["unknown_in_window"][21:41].all()
    assert result.reasons["previous_ratio_unknown"][41]


def test_saved_cutoff_states_survive_future_append_and_restatement() -> None:
    raw = np.full(160, 100.0)
    preserved: list[int] = []
    old_series = None
    old_ma = None
    for stop in range(121, 141):
        # Each cutoff is derived once from its artificial event-adjusted input.
        # The newer event history differs, but it must not overwrite saved D.
        close = raw[:stop].copy()
        close[-1] = 101.0 if stop >= 131 else 99.0
        source = series_of(close)
        ma = moving_averages(source)
        preserved.append(bull_at_cutoff(source, ma).state)
        if stop == 130:
            old_series, old_ma = source, ma
    saved = np.array(preserved, dtype=np.int8)
    before = ratio_cross(saved)
    assert saved.tolist() == [FALSE] * 10 + [TRUE] * 10
    assert before.ratio[-1] == 0.50
    # A future synthetic event changes the latest same-G input history. Reusing
    # those revised prices to rebuild all old D would erase the saved positives.
    revised = series_of(raw[:145].copy())
    assert old_series is not None and old_ma is not None
    old_close = old_series.close.copy()
    wrong_states: list[int] = []
    for stop in range(121, 141):
        prefix = series_of(revised.close[:stop].copy())
        wrong_states.append(bull_at_cutoff(prefix, moving_averages(prefix)).state)
    wrong = np.array(wrong_states, dtype=np.int8)
    assert ratio_cross(wrong).ratio[-1] == 0.0 != before.ratio[-1]
    appended = ratio_cross(np.r_[saved, np.int8(TRUE)])
    np.testing.assert_array_equal(appended.ratio[: len(saved)], before.ratio)
    np.testing.assert_array_equal(old_series.close, old_close)
    assert bull_at_cutoff(old_series, old_ma).state == FALSE
    with pytest.raises(ValueError, match="beyond"):
        replace(revised, decision_cutoff=old_series.decision_cutoff)
    with pytest.raises(ValueError, match="lineage"):
        bull_at_cutoff(old_series, moving_averages(revised))


@pytest.mark.parametrize(
    ("confirmed", "previous", "current", "expected"),
    [(-1, 0, 1, -1), (0, 0, 1, 0), (0, -1, -1, 0), (1, -1, 1, -1), (1, 0, -1, -1), (1, 0, 1, 1), (1, 1, 1, 0), (1, 1, 0, 0), (1, 0, 0, 0)],
)
def test_weekly_turn_confirmation_and_no_next_day_repeat(confirmed: int, previous: int, current: int, expected: int) -> None:
    assert weekly_turn(confirmed_today=confirmed, previous=previous, current=current) == expected
    assert weekly_turn(confirmed_today=FALSE, previous=previous, current=current) == FALSE


def test_density_has_six_same_scale_values_population_std_and_no_rank() -> None:
    source = series_of(np.arange(1, 122, dtype=np.float64), weekly=True)
    result = density_at_cutoff(source, moving_averages(source))
    expected_values = (111.5, 91.5, 61.5, 111.5, 91.5, 61.5)
    np.testing.assert_allclose(np.asarray(result.values, dtype=np.float64), np.asarray(expected_values, dtype=np.float64), rtol=1e-15)
    mean = sum(expected_values) / 6
    hand_std = (sum((value - mean) ** 2 for value in expected_values) / 6) ** 0.5
    assert result.denominator == 121.0 and result.known
    assert result.density == pytest.approx(hand_std / 121, rel=1e-15)
    assert not hasattr(result, "rank") and not hasattr(result, "dense") and not hasattr(result, "percentile")
    constant = series_of(np.full(120, 10.0), weekly=True)
    assert density_at_cutoff(constant, moving_averages(constant)).density == 0.0
    daily = series_of(np.full(120, 10.0))
    with pytest.raises(ValueError, match="completed_weekly"):
        density_at_cutoff(daily, moving_averages(daily))


@pytest.mark.parametrize("last", [0.0, -1.0, np.nan, np.inf])
def test_density_invalid_denominator_is_unknown(last: float) -> None:
    source = series_of(np.r_[np.full(120, 10.0), last], weekly=True)
    result = density_at_cutoff(source, moving_averages(source))
    assert not result.known and result.denominator is None and result.density is None
    assert "denominator:invalid_close" in result.reasons
    young = series_of(np.full(119, 10.0), weekly=True)
    result = density_at_cutoff(young, moving_averages(young))
    assert result.density is None and "ema120:ema_warmup_120" in result.reasons


@pytest.mark.parametrize("field", ["generation", "security_id", "decision_cutoff", "bar_kind", "identical_copy"])
def test_same_length_is_not_sufficient_ma_lineage(field: str) -> None:
    source = series_of(np.arange(1, 151, dtype=np.float64), weekly=True)
    changes: dict[str, Any] = {
        "generation": "other-G",
        "security_id": "FAKE_B",
        "decision_cutoff": source.decision_cutoff + pd.Timedelta(days=1),
        "bar_kind": "daily",
    }
    other = replace(source, **{field: changes[field]}) if field != "identical_copy" else replace(source)
    ma = moving_averages(other)
    for consumer in (bull_at_cutoff, density_at_cutoff):
        with pytest.raises(ValueError, match="lineage"):
            consumer(source, ma)
    forged = MovingAverages(ma.sma, ma.ema, ma.valid, ma.reasons)
    with pytest.raises(ValueError, match="lineage"):
        bull_at_cutoff(source, forged)


@pytest.mark.parametrize(
    "change",
    [
        {"security_id": ""},
        {"generation": " "},
        {"price_basis": "raw"},
        {"bar_kind": "provisional_weekly"},
        {"decision_cutoff": pd.Timestamp("2020-06-01 12:00")},
        {"decision_cutoff": pd.NaT},
        {"decision_cutoff": pd.Timestamp("2020-06-01", tz="Asia/Taipei")},
        {"close": np.ones(121, dtype=np.float32)},
        {"close": np.ones(120, dtype=np.float64)},
        {"close": np.ones((121, 1), dtype=np.float64)},
        {"valid": np.ones(121, dtype=np.int8)},
        {"valid": np.ones(120, dtype=np.bool_)},
        {"bar_dates": pd.date_range("2020-01-01", periods=121, tz="Asia/Taipei")},
        {"bar_dates": pd.date_range("2020-01-01 01:00", periods=121)},
        {"bar_dates": pd.DatetimeIndex([pd.Timestamp("2020-01-01")] * 121)},
        {"bar_dates": pd.date_range("2020-01-01", periods=121)[::-1]},
        {"bar_dates": pd.DatetimeIndex([pd.NaT] * 121)},
        {"decision_cutoff": pd.Timestamp("2020-01-01")},
    ],
)
def test_bad_series_rejected_without_sorting_casting_or_dropping(change: dict[str, Any]) -> None:
    source = series_of(np.ones(121, dtype=np.float64))
    with pytest.raises(ValueError):
        replace(source, **change)


@pytest.mark.parametrize("bad", [np.array([True]), np.array([1.0]), np.array([2], dtype=np.int8), np.array([[1]], dtype=np.int8), np.array([np.nan])])
def test_malformed_ratio_states_are_rejected(bad: NDArray[Any]) -> None:
    with pytest.raises(ValueError, match="integer"):
        ratio_cross(bad)


@pytest.mark.parametrize("bad", [True, np.bool_(False), 0.0, 2, -2])
def test_malformed_weekly_states_are_rejected(bad: Any) -> None:
    for name in ("confirmed_today", "previous", "current"):
        values = {"confirmed_today": 1, "previous": 0, "current": 1}
        values[name] = bad
        with pytest.raises(ValueError, match="integers"):
            weekly_turn(**values)


def test_snapshot_no_mutation_and_empty_results() -> None:
    close = np.arange(1, 151, dtype=np.float64)
    valid = np.ones(len(close), dtype=np.bool_)
    source = series_of(close, valid=valid, weekly=True)
    original_close, original_valid = close.copy(), valid.copy()
    ma = moving_averages(source)
    original = bull_at_cutoff(source, ma), density_at_cutoff(source, ma)
    np.testing.assert_array_equal(close, original_close)
    np.testing.assert_array_equal(valid, original_valid)
    close[:] = 1.0
    valid[:] = False
    assert (bull_at_cutoff(source, ma), density_at_cutoff(source, ma)) == original
    assert not np.shares_memory(close, source.close) and not np.shares_memory(valid, source.valid)
    with pytest.raises(ValueError):
        source.close[0] = 9.0
    with pytest.raises(ValueError):
        ma.ema[120][0] = 9.0
    with pytest.raises(FrozenInstanceError):
        setattr(source, "generation", "changed")
    empty = series_of(np.array([], dtype=np.float64), weekly=True)
    empty_ma = moving_averages(empty)
    assert bull_at_cutoff(empty, empty_ma).state == UNKNOWN
    assert not density_at_cutoff(empty, empty_ma).known
    assert len(ratio_cross(np.array([], dtype=np.int8)).ratio) == 0

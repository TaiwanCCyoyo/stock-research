"""Synthetic arithmetic, causal-history, and proxy-pattern regression tests."""

import numpy as np
import pandas as pd
import pytest

from research_core.feature_atlas_features import _segment, compute_features


def bars(close: np.ndarray | list[float]) -> pd.DataFrame:
    values = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {"Open": values, "High": values + 1, "Low": values - 1, "Close": values, "Turnover": 100.0},
        index=pd.date_range("2020-01-01", periods=len(values)),
    )


@pytest.mark.parametrize("length", range(1, 14))
def test_short_segment_fast_path_equals_complete_calculation(length: int):
    rng = np.random.default_rng(length)
    frame = bars(100 + rng.normal(0, 2, length))
    frame["Open"] = frame.Close + rng.normal(0, 1, length)
    frame["High"] = frame[["Open", "Close"]].max(axis=1) + rng.uniform(0.1, 2, length)
    frame["Low"] = frame[["Open", "Close"]].min(axis=1) - rng.uniform(0.1, 2, length)
    if length >= 3:
        frame.loc[frame.index[:3], ["Open", "High", "Low", "Close"]] = [
            [100, 102, 98, 100],
            [100, 101, 99, 100],
            [103, 104, 102, 103],
        ]
        frame.iloc[1, frame.columns.get_loc("Turnover")] = np.nan
    pd.testing.assert_frame_equal(compute_features(frame), _segment(frame))


def test_fragmented_fast_paths_match_independent_complete_segments():
    lengths = [1, 2, 3, 8, 13, 14, 35]
    frame = bars(100 + np.sin(np.arange(sum(lengths) + len(lengths) - 1)) * 3)
    expected = compute_features(frame).copy()
    expected.loc[:, :] = np.nan
    start = 0
    for length in lengths:
        stop = start + length
        segment = frame.iloc[start:stop].copy()
        reference = _segment(segment)
        expected.loc[segment.index, reference.columns] = reference
        if stop < len(frame):
            frame.iloc[stop] = np.nan
        start = stop + 1
    pd.testing.assert_frame_equal(compute_features(frame), expected)


def test_prefix_and_price_scale_invariance():
    rng = np.random.default_rng(24)
    frame = bars(100 + np.cumsum(rng.normal(0.1, 1, 230)))
    frame["Turnover"] = rng.uniform(1, 200, len(frame))
    full = compute_features(frame)
    for end in (19, 60, 145, 200):
        pd.testing.assert_frame_equal(compute_features(frame.iloc[:end]), full.iloc[:end])
    scaled = frame.copy()
    scaled[["Open", "High", "Low", "Close"]] *= 7.3
    pd.testing.assert_frame_equal(compute_features(scaled), full, atol=1e-10, rtol=1e-10)


def test_prior_high_excludes_today_and_exact_window():
    frame = bars([100.0] * 65)
    frame.iloc[0, frame.columns.get_loc("High")] = 200
    frame.iloc[20, frame.columns.get_loc("Close")] = 102
    frame.iloc[20, frame.columns.get_loc("High")] = 150
    frame.iloc[21, frame.columns.get_loc("Close")] = 151
    result = compute_features(frame)
    assert result.F09.iloc[:20].isna().all()
    assert result.F09.iloc[20] == 0
    assert result.F09.iloc[21] == 1
    assert result.F10.iloc[60] == 0
    frame.iloc[61, frame.columns.get_loc("Close")] = 151
    assert compute_features(frame).F10.iloc[61] == 1


def test_wilder_rsi_atr_and_ema_warmup():
    frame = bars(np.arange(100.0, 150.0))
    result = compute_features(frame)
    assert result.rsi14.iloc[:14].isna().all()
    assert result.rsi14.iloc[14] == 100
    assert result.atr14_pct.iloc[:13].isna().all()
    assert result.atr14_pct.iloc[13] == pytest.approx(2 / 113)
    assert result.adx14.iloc[:27].isna().all()
    assert result.adx14.iloc[27] == 100
    assert result.macd_hist_pct.iloc[:33].isna().all()
    assert result.F29.iloc[:34].isna().all()
    assert compute_features(bars([100.0] * 40)).rsi14.iloc[14] == 50
    assert compute_features(bars(np.arange(150.0, 100.0, -1))).rsi14.iloc[14] == 0


def test_gap_resets_history_but_turnover_gap_is_independent():
    frame = bars(np.arange(100.0, 300.0))
    frame.iloc[70] = np.nan
    result = compute_features(frame)
    assert result.iloc[70].isna().all()
    pd.testing.assert_frame_equal(result.iloc[71:], compute_features(frame.iloc[71:]))
    assert result.F01.iloc[71:90].isna().all()
    assert result.F01.iloc[90] == 1
    frame = bars(np.arange(100.0, 180.0))
    baseline = compute_features(frame)
    frame.iloc[40, frame.columns.get_loc("Turnover")] = np.nan
    result = compute_features(frame)
    pd.testing.assert_series_equal(result.rsi14, baseline.rsi14)
    pd.testing.assert_series_equal(result.F01, baseline.F01)
    assert result.F17.iloc[40:60].isna().all()
    assert result.F18.iloc[40:61].isna().all()
    assert result.F19.iloc[40:60].isna().all()


def test_missing_turnover_on_flat_day_invalidates_direction_sums():
    frame = bars([100.0, 99.0, 100.0] * 30)
    frame.iloc[40, frame.columns.get_loc("Close")] = frame.Close.iloc[39]
    assert compute_features(frame).F19.iloc[40] in (0.0, 1.0)
    frame.iloc[40, frame.columns.get_loc("Turnover")] = np.nan
    result = compute_features(frame)
    assert result.F19.iloc[40:60].isna().all()
    assert pd.notna(result.F19.iloc[60])


def test_zero_turnover_denominators_remain_unknown():
    frame = bars(np.arange(100.0, 150.0))
    result = compute_features(frame)
    assert result.up_down_turnover20.isna().all()
    assert result.F19.isna().all()
    frame["Turnover"] = 0.0
    result = compute_features(frame)
    assert result.F17.isna().all()
    assert result.F18.isna().all()


@pytest.mark.parametrize(
    ("flag", "previous", "current"),
    [
        ("F22", [95, 96, 89, 90], [89, 97, 88, 96]),
        ("F23", [95, 96, 89, 90], [88, 95, 87, 94]),
        ("F24", [95, 96, 89, 90], [91, 94, 90, 93]),
        ("F25", [95, 96, 89, 90], [91, 93, 86, 92]),
    ],
)
def test_handchecked_candles_and_prior_trend(flag: str, previous: list[float], current: list[float]):
    frame = bars([100.0] * 25)
    frame.loc[frame.index[-2], ["Open", "High", "Low", "Close"]] = previous
    frame.loc[frame.index[-1], ["Open", "High", "Low", "Close"]] = current
    result = compute_features(frame)
    assert result[flag].iloc[-1] == 1
    assert result[flag].iloc[:20].isna().all()
    frame.loc[frame.index[:23], ["Open", "Close"]] = 80
    assert compute_features(frame)[flag].iloc[-1] == 0


def test_recovery_support_and_inside_bar_proxies():
    frame = bars([100.0] * 25)
    frame.loc[frame.index[-1], ["Open", "High", "Low", "Close"]] = [100, 102, 98, 101]
    assert compute_features(frame).F20.iloc[-1] == 1
    frame.loc[frame.index[-2], ["Open", "High", "Low", "Close"]] = [99, 100, 97, 98]
    assert compute_features(frame).F21.iloc[-1] == 1
    frame.iloc[-24, frame.columns.get_loc("Low")] = 96
    assert compute_features(frame).F21.iloc[-1] == 0
    frame = bars([100.0, 100.0, 102.0])
    frame.loc[frame.index[1], ["High", "Low"]] = [100.5, 99.5]
    assert compute_features(frame).F26.iloc[-1] == 1


def test_constant_bollinger_and_turnover_arithmetic():
    frame = bars([100.0] * 170)
    result = compute_features(frame)
    assert result.F12.iloc[:143].isna().all()
    assert result.F12.iloc[143] == 1
    assert result.F14.iloc[:163].isna().all()
    assert result.F14.iloc[163] == 0
    frame.iloc[-1, frame.columns.get_loc("Turnover")] = 150
    result = compute_features(frame)
    assert result.turnover_ratio20.iloc[-1] == 1.5
    assert result.F18.iloc[-1] == 1


def test_wilder_recursion_uses_mean_seed():
    frame = bars([100.0] * 16)
    frame.iloc[14, frame.columns.get_loc("High")] = 104
    result = compute_features(frame)
    assert result.atr14_pct.iloc[13] == pytest.approx(2 / 100)
    assert result.atr14_pct.iloc[14] == pytest.approx((2 + (5 - 2) / 14) / 100)


def test_rsi_cross_and_squeeze_followed_by_two_upper_band_closes():
    frame = bars(np.asarray([*np.arange(114.0, 99.0, -1), 110.0]))
    result = compute_features(frame)
    assert pd.isna(result.F27.iloc[14])  # crossing needs prior RSI
    assert result.rsi14.iloc[15] == pytest.approx(1000 / 23)
    assert result.F27.iloc[15] == 1
    frame = bars([100.0] * 165 + [130.0, 140.0])
    result = compute_features(frame)
    assert result.F13.iloc[165] == 0
    assert result.F13.iloc[166] == 1
    assert result.F14.iloc[166] == 1


def test_index_and_price_validation():
    frame = bars([100.0, 101.0])
    with pytest.raises(ValueError, match="sorted unique"):
        compute_features(frame.iloc[::-1])
    frame.iloc[0, frame.columns.get_loc("Close")] = 0
    with pytest.raises(ValueError, match="positive"):
        compute_features(frame)

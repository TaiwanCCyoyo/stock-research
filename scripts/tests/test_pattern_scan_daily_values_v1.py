"""Synthetic local-condition formulas, availability and missing-history cases."""

from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_daily import calculate_daily_features
from research_core.pattern_scan_daily_values_v1 import calculate_common_values
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame


def detector(length: int = 560) -> tuple[pd.DataFrame, pd.DataFrame]:
    positions = np.arange(length)
    close = 100 + positions * 0.03 + 8 * np.sin(positions / 8)
    source = pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "RawClose": close * 1.2,
            "VolumeLots": positions + 100.0,
            "Turnover": close * (positions + 100),
            "Quality": True,
            "quality_reason": "",
        },
        index=pd.bdate_range("2020-01-06", periods=length),
    )
    return prepare_detector_frame(source)


def test_legacy_daily_parity_and_aliases() -> None:
    frame, pivots = detector()
    original = frame.copy(deep=True)
    values = calculate_common_values(frame, pivots)
    raw = frame.copy()
    raw["Close"] = frame.RawClose
    prior = frame.Volume.shift().rolling(20).mean()
    vx = frame.Volume / prior
    liquid = (frame.RawClose * frame.Volume).shift().rolling(20).mean().ge(1000)
    expected = calculate_daily_features(raw, frame, vx.to_numpy(), liquid.to_numpy())
    for column in expected:
        pd.testing.assert_series_equal(values[column], expected[column])
    pd.testing.assert_frame_equal(frame, original)
    assert values.MA_a.iloc[300] == pytest.approx(frame.Close.iloc[300] / frame.SMA20.iloc[300] - 1)
    assert bool(values.MA_b.iloc[300]) == (frame.SMA20.iloc[300] > frame.SMA20.iloc[295])
    assert values.BB_a.iloc[300] == pytest.approx((frame.Close.iloc[300] - frame.BBLower.iloc[300]) / (frame.BBUpper.iloc[300] - frame.BBLower.iloc[300]))
    assert values.BB_b.iloc[300] == pytest.approx((frame.BBWidth.iloc[175:300] <= frame.BBWidth.iloc[300]).mean() * 100)
    assert values.VOL_a.iloc[300] == pytest.approx(frame.Volume.iloc[290:300].mean() / frame.Volume.iloc[240:300].mean())
    assert values.KL_a.iloc[300] == pytest.approx(0.1)
    pd.testing.assert_series_equal(values.RSI, frame.RSI14, check_names=False)
    pd.testing.assert_series_equal(values.ADX, frame.ADX14, check_names=False)
    assert values.MACD.dtype == "boolean"


def test_bollinger_prior_history_and_true_absorbs_unknown() -> None:
    frame, pivots = detector(160)
    frame["BBWidth"] = 10.0
    frame.loc[frame.index[125], "BBWidth"] = 5.0
    frame.loc[frame.index[126], "BBWidth"] = np.nan
    values = calculate_common_values(frame, pivots)
    assert pd.isna(values.BB_b.iloc[124])
    assert values.BB_b.iloc[125] == 0
    assert pd.isna(values.BB_c.iloc[125])  # Today's squeeze is not yet prior.
    assert bool(values.BB_c.iloc[126])
    assert bool(values.BB_c.iloc[130])  # True survives a missing peer.
    assert pd.isna(values.BB_c.iloc[131])


def test_candle_six_days_and_zero_range() -> None:
    frame, pivots = detector(40)
    frame[["F22", "F23", "F24", "F25"]] = 0.0
    frame.loc[frame.index[2], "F22"] = 1.0
    frame.loc[frame.index[3], "F23"] = np.nan
    frame.loc[frame.index[12], ["Open", "High", "Low", "Close"]] = 100.0
    frame.loc[frame.index[12], ["BBUpper", "BBLower"]] = 100.0
    values = calculate_common_values(frame, pivots)
    assert pd.isna(values.KL_c.iloc[1])
    assert bool(values.KL_c.iloc[2])
    assert bool(values.KL_c.iloc[7])
    assert pd.isna(values.KL_c.iloc[8])
    assert not bool(values.KL_c.iloc[9])
    assert pd.isna(values.KL_a.iloc[12]) and pd.isna(values.KL_b.iloc[12]) and pd.isna(values.BB_a.iloc[12])


def test_support_is_available_only_at_confirmation_and_missing_overhead_is_none() -> None:
    frame, pivots = detector(80)
    frame["Close"] = 100.0
    frame["Open"], frame["High"], frame["Low"] = 100.0, 101.0, 99.0
    rows = [
        {"k": 1.5, "kind": "high", "extreme_index": 10, "confirmation_index": 30, "confirmed_at": frame.index[30], "price": 110.0},
        {"k": 1.5, "kind": "low", "extreme_index": 12, "confirmation_index": 35, "confirmed_at": frame.index[35], "price": 90.0},
        {"k": 4.0, "kind": "high", "extreme_index": 11, "confirmation_index": 20, "confirmed_at": frame.index[20], "price": 105.0},
    ]
    values = calculate_common_values(frame, pd.DataFrame(rows))
    assert values.SR_a.iloc[29] == "none"
    assert values.SR_a.iloc[30] == pytest.approx(0.1)
    assert pd.isna(values.SR_b.iloc[34])
    assert values.SR_b.iloc[35] == pytest.approx(100 / 90 - 1)
    frame.loc[frame.index[40], ["Open", "High", "Low", "Close"]] = np.nan
    after_gap = calculate_common_values(frame, pd.DataFrame(rows))
    assert after_gap.SR_a.iloc[41] == pytest.approx(0.1)
    assert after_gap.SR_b.iloc[41] == pytest.approx(100 / 90 - 1)
    rows[0]["confirmed_at"] = frame.index[29]
    with pytest.raises(ValueError, match="timing"):
        calculate_common_values(frame, pd.DataFrame(rows))


@pytest.mark.parametrize("current,expected", [(110.0, "above"), (100.0, "below"), (101.0, "inside")])
def test_volume_profile_prior_window_and_lower_band_tie(current: float, expected: str) -> None:
    frame, pivots = detector(121)
    # All twenty bands have the same volume: choose the lower band [100,101).
    frame["Close"] = np.r_[np.tile(np.arange(100.0, 120.0), 6), current]
    frame["Open"] = frame.Close
    frame["High"], frame["Low"] = frame.Close + 1, frame.Close - 1
    frame["Volume"], frame["VolumeLots"] = 1.0, 1.0
    # Put extra volume at 101: selected band [100.95,101.9), t0 excluded.
    frame.loc[frame.Close.eq(101), "Volume"] = 20.0
    values = calculate_common_values(frame, pivots.iloc[:0])
    assert values.SR_c.iloc[120] == expected
    changed = frame.copy()
    changed.loc[changed.index[120], "Volume"] = 1e12
    assert calculate_common_values(changed, pivots.iloc[:0]).SR_c.iloc[120] == expected
    changed.loc[changed.index[119], "Volume"] = np.nan
    assert pd.isna(calculate_common_values(changed, pivots.iloc[:0]).SR_c.iloc[120])


def test_profile_ties_exact_edges_global_max_and_zero_range() -> None:
    frame, pivots = detector(121)
    frame["Close"] = np.r_[np.tile(np.arange(100.0, 121.0), 5), np.full(15, 100.0), 101.0]
    frame["Open"] = frame.Close
    frame["High"], frame["Low"] = frame.Close + 1, frame.Close - 1
    frame["Volume"], frame["VolumeLots"] = 0.0, 0.0
    result = calculate_common_values(frame, pivots.iloc[:0])
    assert result.SR_c.iloc[120] == "above"  # All-zero tie selects [100,101).
    frame.loc[frame.index[:120], "Volume"] = np.where(frame.Close.iloc[:120].eq(120), 1.0, 0.0)
    frame.loc[frame.index[120], "Close"] = 120.0
    frame.loc[frame.index[120], ["Open", "High", "Low"]] = [120, 121, 119]
    assert calculate_common_values(frame, pivots.iloc[:0]).SR_c.iloc[120] == "inside"
    frame[["Open", "Close"]] = 100.0
    frame["High"], frame["Low"] = 101.0, 99.0
    assert pd.isna(calculate_common_values(frame, pivots.iloc[:0]).SR_c.iloc[120])


@pytest.mark.parametrize("end", [0, 20, 126, 300])
def test_prefix_is_causal(end: int) -> None:
    frame, pivots = detector()
    full = calculate_common_values(frame, pivots)
    subset = cast(pd.DataFrame, pivots[pivots.confirmation_index < end])
    prefix = calculate_common_values(frame.iloc[:end], subset)
    pd.testing.assert_frame_equal(prefix, full.iloc[:end])


def test_gap_history_and_raw_close_limit_are_distinct() -> None:
    frame, pivots = detector()
    frame.loc[frame.index[260], ["Open", "High", "Low", "Close"]] = np.nan
    # Reprepare public indicators so their state also resets at the gap.
    prepared = frame[["Open", "High", "Low", "Close", "RawClose", "VolumeLots", "Turnover", "Quality", "quality_reason"]].copy()
    prepared.loc[prepared.index[260], "quality_reason"] = "gap"
    prepared.loc[prepared.index[262], "RawClose"] = prepared.RawClose.iloc[261] * 1.1
    frame, pivots = prepare_detector_frame(cast(pd.DataFrame, prepared))
    result = calculate_common_values(frame, pivots)
    assert result.C.iloc[260:500].isna().all()
    assert result.BB_b.iloc[260:405].isna().all()
    assert bool(result.G2_limit.iloc[262])
    assert result.quality_reason.iloc[260] == "gap"
    assert result.SR_a.iloc[260] is None
    suffix_frame = frame.iloc[261:]
    suffix_pivots = cast(pd.DataFrame, pivots[pivots.extreme_index >= 261]).copy()
    suffix_pivots["extreme_index"] -= 261
    suffix_pivots["confirmation_index"] -= 261
    suffix = calculate_common_values(suffix_frame, suffix_pivots)
    # Completed-week C4 requires its original calendar prefix; previous raw
    # volume/ATR prefixes can remain known on the first post-gap day.
    columns = ["C", "C2", "C3", "D", "D2", "ret120", "MA_a", "MA_b", "BB_a", "BB_b", "SR_c"]
    pd.testing.assert_frame_equal(result.loc[suffix.index, columns], suffix[columns])

"""Invented-calendar parity and causal-history tests for detector adaptation."""

from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core.derived_features import compute_features as compute_derived
from research_core.feature_atlas_features import _smooth
from research_core.feature_atlas_features import compute_features as compute_atlas
from research_core.feature_atlas_legacy import compute_legacy_features
from research_core.pattern_scan_indicators_v1 import prepare_detector_frame, raw_macd_histogram


def bars(length: int = 540) -> pd.DataFrame:
    positions = np.arange(length)
    close = 100 + positions * 0.04 + 12 * np.sin(positions / 9)
    return pd.DataFrame(
        {
            "Open": close - 0.2,
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "RawClose": close * 2,
            "VolumeLots": positions + 10.0,
            "Turnover": 1000 + positions * 3.0,
            "Quality": True,
            "quality_reason": "",
        },
        index=pd.date_range("2020-01-01", periods=length),
    )


def test_public_feature_parity_raw_units_and_no_mutation() -> None:
    source = bars()
    original = source.copy(deep=True)
    actual, pivots = prepare_detector_frame(source)
    derived, expected_pivots = compute_derived(source)
    atlas = compute_atlas(source)
    legacy = compute_legacy_features(source)
    for name in ("SMA20", "SMA60", "SMA120", "ATR14"):
        pd.testing.assert_series_equal(actual[name], derived[name])
    for output, reference in (("RSI14", "rsi14"), ("ADX14", "adx14"), ("BBWidth", "bb_width20")):
        pd.testing.assert_series_equal(actual[output], atlas[reference], check_names=False)
    for flag in ("F10", "F32", "F22", "F23", "F24", "F25"):
        pd.testing.assert_series_equal(actual[flag], atlas[flag])
    pd.testing.assert_series_equal(actual["F33"], legacy["F33"])
    pd.testing.assert_series_equal(actual["Volume"], source["VolumeLots"], check_names=False)
    pd.testing.assert_series_equal(actual["Turnover"], source["Turnover"])
    pd.testing.assert_series_equal(actual["quality_reason"], source["quality_reason"])
    pd.testing.assert_series_equal(actual["SMA240"], source["Close"].rolling(240).mean(), check_names=False)
    pd.testing.assert_frame_equal(pivots, expected_pivots)
    pd.testing.assert_frame_equal(source, original)
    assert (pivots.confirmed_at >= pivots.extreme_date).all()
    std = cast(pd.Series, source["Close"]).rolling(20).std(ddof=0)
    pd.testing.assert_series_equal(actual["BBUpper"], derived["SMA20"] + 2 * std, check_names=False)
    pd.testing.assert_series_equal(actual["BBLower"], derived["SMA20"] - 2 * std, check_names=False)


def test_macd_reconstructs_raw_level_and_not_normalized_trend() -> None:
    source = bars()
    actual, _ = prepare_detector_frame(source)
    atlas = compute_atlas(source)
    close = cast(pd.Series, source["Close"])
    macd = cast(pd.Series, _smooth(close, 12, 2 / 13) - _smooth(close, 26, 2 / 27))
    expected = cast(pd.Series, macd - _smooth(macd, 9, 2 / 10))
    pd.testing.assert_series_equal(actual["MACDHist"], expected, check_names=False, check_exact=True)
    pd.testing.assert_series_equal(raw_macd_histogram(close), expected, check_names=False, check_exact=True)
    pd.testing.assert_series_equal(cast(pd.Series, actual["MACDHist"] / close), atlas["macd_hist_pct"], check_names=False, check_exact=True)
    assert actual.MACDHist.iloc[:33].isna().all()
    assert pd.notna(actual.MACDHist.iloc[33])
    raw_delta = cast(pd.Series, actual["MACDHist"]).diff()
    normalized_delta = cast(pd.Series, atlas["macd_hist_pct"]).diff()
    assert cast(pd.Series, (raw_delta > 0) != (normalized_delta > 0)).loc[raw_delta.notna() & normalized_delta.notna()].any()


def test_normalized_histogram_round_trip_changes_invented_raw_bytes() -> None:
    source = bars()
    close = cast(pd.Series, source["Close"])
    raw = raw_macd_histogram(close)
    normalized = compute_atlas(source)["macd_hist_pct"]
    round_trip = cast(pd.Series, normalized * close)
    valid = raw.notna().to_numpy(dtype=bool)
    assert np.any(raw.to_numpy()[valid] != round_trip.to_numpy()[valid])
    actual, _ = prepare_detector_frame(source)
    pd.testing.assert_series_equal(actual.MACDHist, raw, check_names=False, check_exact=True)


@pytest.mark.parametrize("invalid", ["quality", "nan", "inf", "negative", "inconsistent"])
def test_gap_resets_indicators_and_preserves_quality_evidence(invalid: str) -> None:
    source = bars()
    gap = 260
    source.loc[source.index[gap], "quality_reason"] = "supplied_jump_gap"
    if invalid == "quality":
        source.loc[source.index[gap], "Quality"] = False
    else:
        source.loc[source.index[gap], "Low"] = {"nan": np.nan, "inf": np.inf, "negative": -1, "inconsistent": 900}[invalid]
    actual, pivots = prepare_detector_frame(source)
    suffix, suffix_pivots = prepare_detector_frame(source.iloc[gap + 1 :])
    pd.testing.assert_frame_equal(actual.iloc[gap + 1 :], suffix)
    observed = cast(pd.DataFrame, pivots[pivots.confirmation_index > gap]).copy()
    observed["confirmation_index"] -= gap + 1
    observed["extreme_index"] -= gap + 1
    pd.testing.assert_frame_equal(observed.reset_index(drop=True), suffix_pivots)
    assert actual.loc[source.index[gap], ["Open", "High", "Low", "Close", "ATR14", "RSI14", "F33"]].isna().all()
    assert actual.loc[source.index[gap], "quality_reason"] == "supplied_jump_gap"
    assert actual.SMA240.iloc[gap : gap + 240].isna().all()
    assert actual.SMA240.iloc[gap + 240] == pytest.approx(source.Close.iloc[gap + 1 : gap + 241].mean())
    assert actual.MACDHist.iloc[gap : gap + 34].isna().all()
    assert pd.notna(actual.MACDHist.iloc[gap + 34])
    pd.testing.assert_series_equal(actual.Volume, source.VolumeLots, check_names=False)


@pytest.mark.parametrize("end", [0, 13, 20, 34, 61, 239, 300])
def test_prefix_is_causal_including_confirmed_pivots(end: int) -> None:
    source = bars()
    full, pivots = prepare_detector_frame(source)
    prefix, prefix_pivots = prepare_detector_frame(source.iloc[:end])
    pd.testing.assert_frame_equal(prefix, full.iloc[:end])
    expected = cast(pd.DataFrame, pivots[pivots.confirmation_index < end]).reset_index(drop=True)
    pd.testing.assert_frame_equal(prefix_pivots, expected)


def test_missing_turnover_does_not_reset_prices_or_restate_volume() -> None:
    source = bars(80)
    source.loc[source.index[40], "Turnover"] = np.inf
    source.loc[source.index[41], "VolumeLots"] = np.nan
    actual, _ = prepare_detector_frame(source)
    assert pd.notna(actual.SMA60.iloc[59])
    assert np.isinf(actual.Turnover.iloc[40])
    assert pd.isna(actual.Volume.iloc[41])


@pytest.mark.parametrize("invalid", ["duplicate", "unsorted", "timezone", "intraday", "missing_date", "missing_column", "nonnumeric"])
def test_calendar_and_input_validation(invalid: str) -> None:
    source = bars(30)
    if invalid == "duplicate":
        source.index = pd.DatetimeIndex([source.index[0]] * len(source))
    elif invalid == "unsorted":
        source = source.iloc[::-1]
    elif invalid == "timezone":
        source.index = cast(pd.DatetimeIndex, source.index).tz_localize("Asia/Taipei")
    elif invalid == "intraday":
        source.index = source.index + pd.Timedelta(hours=1)
    elif invalid == "missing_date":
        source.index = pd.DatetimeIndex([pd.NaT, *source.index[1:]])
    elif invalid == "missing_column":
        source = source.drop(columns="VolumeLots")
    else:
        source["Close"] = "bad"
    with pytest.raises(ValueError):
        prepare_detector_frame(source)

"""Synthetic formula checks and parity with the frozen detect.py algorithm."""

from typing import cast

import numpy as np
import pandas as pd
import pytest
from numpy.typing import ArrayLike

from research_core.derived_features import compute_features, definition_metadata


def frame(close: ArrayLike) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {"Open": close, "High": close + 1, "Low": close - 1, "Close": close, "Quality": True, "RawClose": close.copy()},
        index=pd.date_range("2020-01-01", periods=len(close)),
    )


def frozen_pivots_atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, atr: np.ndarray, k: float):  # noqa: E741 - frozen reference names
    """Verbatim function body from frozen 20261005-hhhl-examples/detect.py."""
    ph, pl = [], []
    mode, ext_i = 0, 0
    for i in range(1, len(c)):
        a = atr[i]
        if not np.isfinite(a) or a <= 0:
            continue
        if mode == 0:
            mode, ext_i = 1, i
            continue
        if mode == 1:
            if h[i] >= h[ext_i]:
                ext_i = i
            elif h[ext_i] - l[i] >= k * a:
                ph.append((ext_i, i, h[ext_i]))
                mode, ext_i = -1, i
        else:
            if l[i] <= l[ext_i]:
                ext_i = i
            elif h[i] - l[ext_i] >= k * a:
                pl.append((ext_i, i, l[ext_i]))
                mode, ext_i = 1, i
    return ph, pl


def test_wilder_seed_recursion_and_input_preservation():
    prepared = frame(np.r_[np.full(14, 100), 110, 110])
    original = prepared.copy(deep=True)
    daily, _ = compute_features(prepared)
    assert daily.ATR14.iloc[:13].isna().all()
    assert daily.ATR14.iloc[13] == 2
    expected = (13 * 2 + 11) / 14
    assert daily.ATR14.iloc[14] == pytest.approx(expected)
    assert daily.ATR14.iloc[15] == pytest.approx((13 * expected + 2) / 14)
    assert daily.atr14_pct.iloc[14] == pytest.approx(expected / 110)
    pd.testing.assert_frame_equal(prepared, original)
    pd.testing.assert_series_equal(daily.RawClose, prepared.RawClose)


@pytest.mark.parametrize("invalid", ["quality", "missing", "infinite", "negative", "inconsistent"])
def test_invalid_rows_reset_all_state_and_keep_calendar(invalid: str):
    prepared = frame(np.r_[np.full(20, 100), np.full(21, 200)])
    if invalid == "quality":
        prepared.loc[prepared.index[20], "Quality"] = False
    else:
        value = {"missing": np.nan, "infinite": np.inf, "negative": -1, "inconsistent": 300}[invalid]
        prepared.loc[prepared.index[20], "Low"] = value
    daily, pivots = compute_features(prepared)
    assert daily.index.equals(prepared.index)
    assert daily.ATR14.iloc[20:34].isna().all()
    assert daily.ATR14.iloc[34] == 2  # first post-gap TR ignores pre-gap close
    assert daily.SMA5.iloc[20:25].isna().all()
    assert daily.EMA5.iloc[20:25].isna().all()
    assert daily.BB20_Middle.iloc[20:40].isna().all()
    assert pivots.empty  # cross-gap jump cannot confirm an earlier high


def test_tie_extreme_confirmation_and_unconfirmed_endpoint():
    prepared = frame(np.r_[np.full(14, 100), 100, 96, 96, 100, 100])
    _, pivots = compute_features(prepared)
    small = cast(pd.DataFrame, pivots[pivots.k == 1.5]).reset_index(drop=True)
    assert small.kind.tolist() == ["high", "low"]
    assert small.extreme_index.tolist() == [14, 16]
    assert small.confirmation_index.tolist() == [15, 17]
    assert small.extreme_date.tolist() == [prepared.index[14], prepared.index[16]]
    assert small.confirmed_at.tolist() == [prepared.index[15], prepared.index[17]]
    assert small.price.tolist() == [101, 95]
    assert not (small.extreme_index == 18).any()
    assert pivots[pivots.k == 4].empty


@pytest.mark.parametrize("k", [1.5, 4.0])
def test_direct_frozen_algorithm_parity_and_prefix_consistency(k: float):
    # Oscillating smooth ranges produce multiple confirmed highs and lows for both k.
    prepared = frame(100 + 20 * np.sin(np.arange(160) / 7))
    daily, pivots = compute_features(prepared)
    expected = frozen_pivots_atr(prepared.High.to_numpy(), prepared.Low.to_numpy(), prepared.Close.to_numpy(), daily.ATR14.to_numpy(), k)
    selected = cast(pd.DataFrame, pivots[pivots.k == k])
    for kind, rows in zip(("high", "low"), expected):
        actual = cast(pd.DataFrame, selected[selected.kind == kind])
        assert list(cast(pd.DataFrame, actual[["extreme_index", "confirmation_index", "price"]]).itertuples(index=False, name=None)) == rows
        assert rows
    for length in (1, 13, 14, 15, 30, 60, 100, 159):
        prefix_daily, prefix_pivots = compute_features(prepared.iloc[:length])
        pd.testing.assert_frame_equal(prefix_daily, daily.iloc[:length])
        expected_prefix = cast(pd.DataFrame, selected[selected.confirmation_index < length]).reset_index(drop=True)
        pd.testing.assert_frame_equal(cast(pd.DataFrame, prefix_pivots[prefix_pivots.k == k]).reset_index(drop=True), expected_prefix)


def test_gap_pivot_indices_remain_global_and_prefix_consistent():
    prepared = frame(100 + 20 * np.sin(np.arange(100) / 4))
    prepared.loc[prepared.index[35], "Quality"] = False
    _, pivots = compute_features(prepared)
    assert not ((pivots.extreme_index < 35) & (pivots.confirmation_index > 35)).any()
    assert not pivots.confirmation_index.between(35, 48).any()
    assert (pivots.extreme_index > 48).any()
    _, prefix = compute_features(prepared.iloc[:75])
    expected = cast(pd.DataFrame, pivots[pivots.confirmation_index < 75]).reset_index(drop=True)
    pd.testing.assert_frame_equal(prefix, expected)


def test_convenience_formulas_and_market_calendar_spacing():
    prepared = frame(np.arange(10, 140))
    prepared.index = pd.bdate_range("2020-01-01", periods=len(prepared))
    daily, _ = compute_features(prepared)
    assert daily.SMA5.iloc[4] == 12
    assert daily.EMA5.iloc[4] == 12
    assert daily.EMA5.iloc[5] == 13
    assert daily.SMA120.iloc[119] == pytest.approx(np.mean(np.arange(10, 130)))
    assert daily.BB20_Middle.iloc[19] == 19.5
    assert daily.BB20_Upper.iloc[19] == pytest.approx(19.5 + 2 * np.std(np.arange(10, 30), ddof=0))
    assert daily.BB20_Lower.iloc[19] == pytest.approx(19.5 - 2 * np.std(np.arange(10, 30), ddof=0))
    assert daily.ATR14.iloc[13] == 2
    assert definition_metadata()["atr14_pct"].startswith("ATR14 / Close")


def test_empty_schema_and_all_invalid_schema():
    empty_daily, empty_pivots = compute_features(frame([]))
    daily, pivots = compute_features(frame([100]))
    assert empty_daily.columns.tolist() == daily.columns.tolist()
    assert empty_pivots.dtypes.equals(pivots.dtypes)
    assert empty_pivots.columns.tolist() == ["k", "kind", "extreme_index", "confirmation_index", "extreme_date", "confirmed_at", "price"]
    prepared = frame([100, 100])
    prepared["Quality"] = pd.Series([pd.NA, False], index=prepared.index, dtype="boolean")
    daily, pivots = compute_features(prepared)
    assert daily.ATR14.isna().all() and pivots.empty


@pytest.mark.parametrize("case", ["missing", "unsorted", "duplicate", "timezone", "intraday", "nat", "index", "text", "bool", "duplicate_column"])
def test_invalid_input_contract(case: str):
    prepared = frame([100, 101])
    if case == "missing":
        prepared = prepared.drop(columns="Quality")
    elif case == "unsorted":
        prepared = prepared.iloc[::-1]
    elif case == "duplicate":
        prepared.index = pd.DatetimeIndex([prepared.index[0]] * 2)
    elif case == "timezone":
        prepared.index = pd.DatetimeIndex(prepared.index).tz_localize("UTC")
    elif case == "intraday":
        prepared.index += pd.Timedelta(hours=1)
    elif case == "nat":
        prepared.index = pd.DatetimeIndex([prepared.index[0], pd.NaT])
    elif case == "index":
        prepared = prepared.reset_index(drop=True)
    elif case == "text":
        prepared["Open"] = "100"
    elif case == "bool":
        prepared["Open"] = True
    elif case == "duplicate_column":
        prepared = pd.concat([prepared, prepared[["Open"]]], axis=1)
    with pytest.raises(ValueError):
        compute_features(prepared)


def test_non_dataframe_rejected():
    with pytest.raises(TypeError):
        compute_features(cast(pd.DataFrame, None))  # Exercise runtime validation deliberately.

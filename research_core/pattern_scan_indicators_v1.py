"""Public-feature adapter for one stock on an already padded session calendar."""

from __future__ import annotations

import logging
from typing import cast

import numpy as np
import pandas as pd

from research_core.derived_features import compute_features as compute_derived
from research_core.feature_atlas_features import _smooth
from research_core.feature_atlas_features import compute_features as compute_atlas
from research_core.feature_atlas_legacy import compute_legacy_features

LOGGER = logging.getLogger(__name__)
OHLC = ("Open", "High", "Low", "Close")
RAW_NUMERIC = ("RawClose", "VolumeLots", "Turnover")
ATLAS_FLAGS = ("F10", "F32", "F22", "F23", "F24", "F25")


def raw_macd_histogram(close: pd.Series) -> pd.Series:
    """Expose the atlas EMA kernel's raw histogram without normalization loss.

    The caller supplies quality-masked adjusted closes. The shared kernel
    resets at NaN, seeds MACD after 26 prices and its signal after 34 prices.
    Avoid dividing and multiplying by Close: that round trip can change an
    exact adjacent-histogram comparison by one floating-point ULP.
    """
    macd = cast(pd.Series, _smooth(close, 12, 2 / 13) - _smooth(close, 26, 2 / 27))
    return cast(pd.Series, macd - _smooth(macd, 9, 2 / 10))


def prepare_detector_frame(prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return causal detector inputs and unchanged confirmed public pivots.

    Prices must already be adjusted and padded to the common daily calendar.
    Invalid OHLC or supplied Quality resets every price indicator. Volume is
    the untouched raw lot series; Turnover remains raw thousand TWD, with
    invalid turnover unknown for turnover calculations only. quality_reason
    remains the caller's original evidence; this function invents no overlays.
    MACDHist retains the atlas kernel's raw histogram without a normalization
    round trip, so exact raw-level trend comparisons retain their meaning.
    """
    if not isinstance(prepared, pd.DataFrame):
        raise TypeError("prepared must be a DataFrame")
    required = {*OHLC, *RAW_NUMERIC, "Quality", "quality_reason"}
    missing = required - set(prepared.columns)
    if missing or not prepared.columns.is_unique:
        raise ValueError(f"missing required columns or duplicate columns: {sorted(missing)}")
    for column in (*OHLC, *RAW_NUMERIC):
        if not pd.api.types.is_numeric_dtype(prepared[column]) or pd.api.types.is_bool_dtype(prepared[column]):
            raise ValueError(f"{column} must be numeric")
    data = prepared.copy(deep=True)
    prices = cast(pd.DataFrame, data.loc[:, OHLC]).to_numpy(dtype=float, na_value=np.nan)
    valid = data["Quality"].eq(True).fillna(False).to_numpy(dtype=bool)
    valid &= np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    opening, high, low, close = prices.T
    valid &= (high >= low) & (opening >= low) & (opening <= high) & (close >= low) & (close <= high)
    data.loc[~valid, list(OHLC)] = np.nan
    data["Quality"] = valid
    daily, pivots = compute_derived(data)  # Also validates the daily calendar.
    atlas_input = data.copy(deep=True)
    turnover = cast(pd.Series, data["Turnover"])
    atlas_input["Turnover"] = turnover.where(np.isfinite(turnover) & (turnover >= 0))
    atlas = compute_atlas(atlas_input)
    legacy = compute_legacy_features(data)
    daily["Volume"] = data["VolumeLots"].copy()
    daily["SMA240"] = cast(pd.Series, data["Close"]).rolling(240, min_periods=240).mean()
    daily["RSI14"] = atlas["rsi14"]
    daily["ADX14"] = atlas["adx14"]
    daily["MACDHist"] = raw_macd_histogram(cast(pd.Series, data["Close"]))
    daily["BBUpper"] = daily["BB20_Upper"]
    daily["BBLower"] = daily["BB20_Lower"]
    daily["BBWidth"] = atlas["bb_width20"]
    for flag in ATLAS_FLAGS:
        daily[flag] = atlas[flag]
    daily["F33"] = legacy["F33"]
    LOGGER.debug("Prepared detector indicators rows=%d valid=%d pivots=%d", len(daily), int(valid.sum()), len(pivots))
    return daily, pivots

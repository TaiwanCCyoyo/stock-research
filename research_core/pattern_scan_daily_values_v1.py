"""Causal per-stock scan conditions over supplied common-calendar indicators."""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_daily import calculate_daily_features

LOGGER = logging.getLogger(__name__)


def _boolean(condition: pd.Series, known: pd.Series) -> pd.Series:
    return cast(pd.Series, condition.astype("boolean").where(known))


def _any_window(values: pd.Series, window: int) -> pd.Series:
    true = cast(pd.Series, values.eq(True).fillna(False).astype(float).rolling(window, min_periods=1).max()).eq(1)
    known = cast(pd.Series, values.notna().rolling(window, min_periods=window).sum()).eq(window)
    return _boolean(cast(pd.Series, true), cast(pd.Series, true | known))


def _profile(close: np.ndarray, volume: np.ndarray, current: float) -> str | None:
    if not np.isfinite(current) or not np.isfinite(close).all() or not np.isfinite(volume).all() or (volume < 0).any():
        return None
    low, high = float(close.min()), float(close.max())
    if low == high:
        return None
    edges = np.linspace(low, high, 21)
    bands = np.minimum(np.searchsorted(edges, close, side="right") - 1, 19)
    totals = np.bincount(bands, weights=volume, minlength=20)
    selected = int(np.argmax(totals))  # First maximum is the lower band.
    if current < edges[selected]:
        return "below"
    if current >= edges[selected + 1] and (selected != 19 or current > high):
        return "above"
    return "inside"


def _support_resistance(frame: pd.DataFrame, pivots: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    required = {"k", "kind", "extreme_index", "confirmation_index", "confirmed_at", "price"}
    if not required.issubset(pivots) or not pivots.columns.is_unique:
        raise ValueError("pivots require the public confirmed-pivot schema")
    ordered = pivots.sort_values(["confirmation_index", "extreme_index"], kind="stable")
    records: list[tuple[int, str, float]] = []
    for supplied_row in ordered.itertuples(index=False):
        row = cast(Any, supplied_row)
        confirmation = int(row.confirmation_index)
        extreme = int(row.extreme_index)
        if confirmation != row.confirmation_index or extreme != row.extreme_index or not 0 <= extreme <= confirmation < len(frame):
            raise ValueError("pivot indices must be valid ordered calendar positions")
        if pd.Timestamp(row.confirmed_at) != frame.index[confirmation] or row.kind not in {"high", "low"} or not np.isfinite(row.price) or row.price <= 0:
            raise ValueError("pivot timing, kind or price is invalid")
        if row.k == 1.5:
            records.append((confirmation, row.kind, float(row.price)))
    above: list[float | str | None] = []
    below: list[float] = []
    cursor = 0
    highs: list[float] = []
    lows: list[float] = []
    for index, value in enumerate(frame["Close"].to_numpy(dtype=float, na_value=np.nan)):
        while cursor < len(records) and records[cursor][0] <= index:
            _, kind, price = records[cursor]
            (highs if kind == "high" else lows).append(price)
            cursor += 1
        if not np.isfinite(value):
            above.append(None)
            below.append(np.nan)
            continue
        overhead = [price for price in reversed(highs) if price > value]
        support = [price for price in reversed(lows) if price < value]
        above.append(min(overhead) / value - 1 if overhead else "none")
        below.append(value / max(support) - 1 if support else np.nan)
    return pd.Series(above, index=frame.index, dtype=object), pd.Series(below, index=frame.index, dtype=float)


def calculate_common_values(frame: pd.DataFrame, pivots: pd.DataFrame) -> pd.DataFrame:
    """Calculate local values; selection, global ranks and event S/L stay external.

    Previous windows exclude t0. Shared legacy numerical values and their
    reason columns are returned unchanged; aliases use supplied public indicators.
    SR pivots become usable at confirmation and retain their historical identity.
    Missing current prices make the lookup unknown without expiring old pivots.
    No data is
    read, mutated, filled, dropped or retrospectively promoted to availability.
    """
    required = {
        "Open",
        "High",
        "Low",
        "Close",
        "RawClose",
        "VolumeLots",
        "Volume",
        "SMA20",
        "BBUpper",
        "BBLower",
        "BBWidth",
        "RSI14",
        "MACDHist",
        "ADX14",
        "F22",
        "F23",
        "F24",
        "F25",
        "quality_reason",
    }
    if not required.issubset(frame) or not frame.columns.is_unique:
        raise ValueError("detector frame is missing required columns or has duplicates")
    close = cast(pd.Series, frame["Close"])
    volume = cast(pd.Series, frame["Volume"]).where(np.isfinite(frame["Volume"]) & frame["Volume"].ge(0))
    prior20 = cast(pd.Series, volume.shift().rolling(20, min_periods=20).mean())
    vx = cast(pd.Series, volume / prior20.where(prior20 > 0))
    raw = frame.copy(deep=True)
    raw["Close"] = frame["RawClose"]
    liquid = (frame["RawClose"] * volume).shift().rolling(20, min_periods=20).mean().ge(1000)
    result = calculate_daily_features(raw, frame, vx.to_numpy(dtype=float, na_value=np.nan), liquid.to_numpy(dtype=bool))
    result["quality_reason"] = frame["quality_reason"].copy()
    ma20 = cast(pd.Series, frame["SMA20"])
    result["MA_a"] = close / ma20.where(ma20 > 0) - 1
    prior_ma = ma20.shift(5)
    # A gap between endpoints invalidates a slope even if both ends are known.
    result["MA_b"] = _boolean(cast(pd.Series, ma20 > prior_ma), cast(pd.Series, ma20.rolling(6, min_periods=6).count().eq(6)))
    spread = cast(pd.Series, frame["BBUpper"] - frame["BBLower"])
    result["BB_a"] = (close - frame["BBLower"]) / spread.where(spread > 0)
    width = cast(pd.Series, frame["BBWidth"])
    result["BB_b"] = width.rolling(126, min_periods=126).apply(lambda values: np.count_nonzero(values[:-1] <= values[-1]) / 125 * 100, raw=True)
    prior_min = width.shift().rolling(125, min_periods=125).min()
    squeeze = _boolean(cast(pd.Series, width <= prior_min), cast(pd.Series, width.notna() & prior_min.notna()))
    result["BB_c"] = _any_window(cast(pd.Series, squeeze.shift()), 5)
    result["SR_a"], result["SR_b"] = _support_resistance(frame, pivots)
    result["SR_a_unknown_reason"] = pd.Series(None, index=frame.index, dtype=object).where(close.notna(), "missing_price")
    result["SR_b_unknown_reason"] = pd.Series(None, index=frame.index, dtype=object).where(result["SR_b"].notna(), "no_confirmed_support")
    result.loc[close.isna(), "SR_b_unknown_reason"] = "missing_price"
    profile: list[str | None] = [None] * len(frame)
    closes = close.to_numpy(dtype=float, na_value=np.nan)
    volumes = volume.to_numpy(dtype=float, na_value=np.nan)
    for index in range(120, len(frame)):
        profile[index] = _profile(closes[index - 120 : index], volumes[index - 120 : index], closes[index])
    result["SR_c"] = pd.Series(profile, index=frame.index, dtype=object)
    candle_range = cast(pd.Series, frame["High"] - frame["Low"])
    denominator = candle_range.where(candle_range > 0)
    result["KL_a"] = (close - frame["Open"]).abs() / denominator
    result["KL_b"] = (frame["High"] - frame[["Open", "Close"]].max(axis=1)) / denominator
    flags = cast(pd.DataFrame, frame[["F22", "F23", "F24", "F25"]])
    any_candle = flags.eq(1).any(axis=1)
    candle = _boolean(cast(pd.Series, any_candle), cast(pd.Series, any_candle | flags.notna().all(axis=1)))
    result["KL_c"] = _any_window(candle, 6)
    result["RSI"] = frame["RSI14"]
    hist = cast(pd.Series, frame["MACDHist"])
    result["MACD"] = _boolean(cast(pd.Series, (hist > 0) & (hist > hist.shift())), cast(pd.Series, hist.notna() & hist.shift().notna()))
    result["ADX"] = frame["ADX14"]
    prior60 = cast(pd.Series, volume.shift().rolling(60, min_periods=60).mean())
    result["VOL_a"] = volume.shift().rolling(10, min_periods=10).mean() / prior60.where(prior60 > 0)
    LOGGER.debug("Calculated common scan conditions rows=%d confirmed_pivots=%d", len(result), len(pivots))
    return result

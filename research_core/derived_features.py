"""Pure, gap-reset daily features and confirmation-time ATR pivots."""

from __future__ import annotations

import logging
from typing import Any, cast

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
OHLC = ("Open", "High", "Low", "Close")
SMA_PERIODS = (5, 10, 20, 60, 120)
EMA_PERIODS = (5, 10, 20, 60)
PIVOT_K = (1.5, 4.0)
PIVOT_DTYPES = {
    "k": "float64",
    "kind": "object",
    "extreme_index": "int64",
    "confirmation_index": "int64",
    "extreme_date": "datetime64[ns]",
    "confirmed_at": "datetime64[ns]",
    "price": "float64",
}


def definition_metadata() -> dict[str, Any]:
    """Return serializable formulas, availability and missing-data semantics."""
    return {
        "version": "derived-features.v1",
        "gap_policy": "Every invalid calendar row resets all state; never fill or drop rows.",
        "validity": "Quality == True and finite positive consistent OHLC.",
        "ATR14": "First TR=High-Low; thereafter max(High-Low,abs(High-prevClose),abs(Low-prevClose)); seed mean of 14 TR; Wilder (13*prevATR+TR)/14.",
        "atr14_pct": "ATR14 / Close (fraction, not percentage points).",
        "SMA": {"periods": list(SMA_PERIODS), "formula": "Arithmetic mean of n closes; requires n consecutive valid rows."},
        "EMA": {"periods": list(EMA_PERIODS), "formula": "Seed mean of first n closes; then alpha*Close+(1-alpha)*prevEMA, alpha=2/(n+1)."},
        "BB20": "BB20_Middle=SMA20; BB20_Upper/Lower=Middle +/- 2*population std of 20 closes (ddof=0).",
        "pivots": {
            "k": list(PIVOT_K),
            "formula": (
                "Start tracking high at first positive usable ATR; equal high/low updates latest extreme before reversal check; "
                "confirm on opposite range >= k*currentATR."
            ),
            "availability": "Confirmed only at confirmed_at; extreme_date is retrospective location, not availability; final unconfirmed endpoint omitted.",
            "indices": "Zero-based positions in the entire supplied calendar, including invalid rows.",
        },
    }


def _validate(prepared: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(prepared, pd.DataFrame):
        raise TypeError("prepared must be a DataFrame")
    index = prepared.index
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("prepared requires a DatetimeIndex")
    if index.tz is not None or index.hasnans or not index.is_unique or not index.is_monotonic_increasing:
        raise ValueError("calendar must be sorted, unique, timezone-naive and nonmissing")
    if any(day != day.normalize() for day in index):
        raise ValueError("calendar must contain daily midnight dates")
    missing = set((*OHLC, "Quality")) - set(prepared.columns)
    if missing or not prepared.columns.is_unique:
        raise ValueError(f"missing required columns or duplicate columns: {sorted(missing)}")
    if any(not pd.api.types.is_numeric_dtype(prepared[col]) or pd.api.types.is_bool_dtype(prepared[col]) for col in OHLC):
        raise ValueError("OHLC columns must be numeric")
    prices = prepared.loc[:, OHLC].to_numpy(dtype=float, na_value=np.nan)
    valid = prepared["Quality"].eq(True).fillna(False).to_numpy(dtype=bool)
    valid &= np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    opening, high, low, close = prices.T
    valid &= (high >= low) & (opening >= low) & (opening <= high) & (close >= low) & (close <= high)
    return prices, valid


def _atr(prices: np.ndarray, valid: np.ndarray) -> np.ndarray:
    result = np.full(len(prices), np.nan)
    count, seed, previous_close, previous_atr = 0, 0.0, 0.0, np.nan
    for i, (_, high, low, close) in enumerate(prices):
        if not valid[i]:
            count, seed, previous_atr = 0, 0.0, np.nan
            continue
        tr = high - low if count == 0 else max(high - low, abs(high - previous_close), abs(low - previous_close))
        count += 1
        if count <= 14:
            seed += tr
            if count == 14:
                previous_atr = seed / 14
        else:
            previous_atr = (13 * previous_atr + tr) / 14
        result[i], previous_close = previous_atr, close
    return result


def _convenience(daily: pd.DataFrame, close: np.ndarray, valid: np.ndarray) -> None:
    columns = [*(f"SMA{n}" for n in SMA_PERIODS), *(f"EMA{n}" for n in EMA_PERIODS), "BB20_Middle", "BB20_Upper", "BB20_Lower"]
    for column in columns:
        daily[column] = np.nan
    starts: np.ndarray = np.flatnonzero(valid & ~np.r_[False, valid[:-1]]) if len(valid) else np.array([], dtype=int)
    stops: np.ndarray = np.flatnonzero(valid & ~np.r_[valid[1:], False]) + 1 if len(valid) else np.array([], dtype=int)
    for start, stop in zip(starts, stops):
        values = pd.Series(close[start:stop])
        for n in SMA_PERIODS:
            daily.iloc[start:stop, daily.columns.get_loc(f"SMA{n}")] = np.asarray(values.rolling(n).mean())
        for n in EMA_PERIODS:
            ema = np.full(len(values), np.nan)
            if len(values) >= n:
                ema[n - 1] = float(values.iloc[:n].mean())
                alpha = 2 / (n + 1)
                for i in range(n, len(values)):
                    ema[i] = alpha * values.iloc[i] + (1 - alpha) * ema[i - 1]
            daily.iloc[start:stop, daily.columns.get_loc(f"EMA{n}")] = ema
        middle, std = values.rolling(20).mean(), values.rolling(20).std(ddof=0)
        for column, feature in (("BB20_Middle", middle), ("BB20_Upper", middle + 2 * std), ("BB20_Lower", middle - 2 * std)):
            daily.iloc[start:stop, daily.columns.get_loc(column)] = np.asarray(feature)


def _pivots(prices: np.ndarray, valid: np.ndarray, atr: np.ndarray, dates: pd.DatetimeIndex) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for k in PIVOT_K:
        mode, extreme = 0, 0
        for i, (_, high, low, _) in enumerate(prices):
            if not valid[i]:
                mode = 0
                continue
            if not np.isfinite(atr[i]) or atr[i] <= 0:
                continue
            if mode == 0:
                mode, extreme = 1, i
                continue
            if mode == 1 and high >= prices[extreme, 1]:
                extreme = i
            elif mode == -1 and low <= prices[extreme, 2]:
                extreme = i
            elif (mode == 1 and prices[extreme, 1] - low >= k * atr[i]) or (mode == -1 and high - prices[extreme, 2] >= k * atr[i]):
                records.append({
                    "k": k,
                    "kind": "high" if mode == 1 else "low",
                    "extreme_index": extreme,
                    "confirmation_index": i,
                    "extreme_date": dates[extreme],
                    "confirmed_at": dates[i],
                    "price": prices[extreme, 1 if mode == 1 else 2],
                })
                mode, extreme = -mode, i
    return pd.DataFrame(records, columns=pd.Index(PIVOT_DTYPES)).astype(PIVOT_DTYPES)


def compute_features(prepared: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute features without mutating, dropping or filling supplied calendar rows."""
    prices, valid = _validate(prepared)
    daily = prepared.copy(deep=True)
    atr = _atr(prices, valid)
    daily["ATR14"] = atr
    daily["atr14_pct"] = atr / prices[:, 3]
    _convenience(daily, prices[:, 3], valid)
    pivots = _pivots(prices, valid, atr, cast(pd.DatetimeIndex, prepared.index))
    LOGGER.debug("Computed derived features rows=%d valid=%d pivots=%d", len(daily), int(valid.sum()), len(pivots))
    return daily, pivots

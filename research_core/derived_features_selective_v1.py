"""Selective API v1; numerical helpers copied from frozen derived-features.v1."""

from __future__ import annotations

import logging
from collections.abc import Iterable
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
        "version": "derived-features-selective.v1",
        "numerical_definition_version": "derived-features.v1",
        "gap_policy": "Every invalid calendar row resets all state; never fill or drop rows.",
        "validity": "Quality == True and finite positive consistent OHLC.",
        "ATR14": ("First TR=High-Low; thereafter max(High-Low,abs(High-prevClose),abs(Low-prevClose)); seed mean of 14 TR; Wilder (13*prevATR+TR)/14."),
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
            "availability": ("Confirmed only at confirmed_at; extreme_date is retrospective location, not availability; final unconfirmed endpoint omitted."),
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


def _pivots(prices: np.ndarray, valid: np.ndarray, atr: np.ndarray, dates: pd.DatetimeIndex, ks: tuple[float, ...]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for k in ks:
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


BB_COLUMNS = ("BB20_Middle", "BB20_Upper", "BB20_Lower")
DAILY_FEATURES = (
    "ATR14",
    "atr14_pct",
    *(f"SMA{n}" for n in SMA_PERIODS),
    *(f"EMA{n}" for n in EMA_PERIODS),
    *BB_COLUMNS,
)
PIVOT_FEATURES = {"pivots_1p5": 1.5, "pivots_4": 4.0}
ALL_FEATURES = (*DAILY_FEATURES, *PIVOT_FEATURES)


def _requests(features: Iterable[str]) -> set[str]:
    if isinstance(features, (str, bytes)):
        raise TypeError("features must be an iterable of feature names, not a string")
    requested = tuple(features)
    if any(not isinstance(feature, str) for feature in requested):
        raise TypeError("feature names must be strings")
    if len(set(requested)) != len(requested):
        raise ValueError("duplicate feature requests")
    unknown = set(requested) - set(ALL_FEATURES)
    if unknown:
        raise ValueError(f"unknown feature requests: {sorted(unknown)}")
    return set(requested)


def _ema(values: pd.Series, n: int) -> np.ndarray:
    # Preserve the v1 arithmetic order and mean seed exactly.
    ema = np.full(len(values), np.nan)
    if len(values) >= n:
        ema[n - 1] = float(values.iloc[:n].mean())
        alpha = 2 / (n + 1)
        for i in range(n, len(values)):
            ema[i] = alpha * values.iloc[i] + (1 - alpha) * ema[i - 1]
    return ema


def _rolling_mean(values: pd.Series, n: int) -> np.ndarray:
    return np.asarray(values.rolling(n).mean())


def _rolling_std(values: pd.Series) -> np.ndarray:
    return np.asarray(values.rolling(20).std(ddof=0))


def _selected_convenience(daily: pd.DataFrame, close: np.ndarray, valid: np.ndarray, requested: set[str]) -> None:
    starts = np.flatnonzero(valid & ~np.r_[False, valid[:-1]]) if len(valid) else np.array([], dtype=int)
    stops = np.flatnonzero(valid & ~np.r_[valid[1:], False]) + 1 if len(valid) else np.array([], dtype=int)
    for start, stop in zip(starts, stops):
        values = pd.Series(close[start:stop])
        means: dict[int, np.ndarray] = {}
        for n in SMA_PERIODS:
            if f"SMA{n}" in requested:
                means[n] = _rolling_mean(values, n)
                daily.iloc[start:stop, daily.columns.get_loc(f"SMA{n}")] = means[n]
        for n in EMA_PERIODS:
            if f"EMA{n}" in requested:
                daily.iloc[start:stop, daily.columns.get_loc(f"EMA{n}")] = _ema(values, n)
        if requested.intersection(BB_COLUMNS):
            middle = means[20] if 20 in means else _rolling_mean(values, 20)
            if "BB20_Middle" in requested:
                daily.iloc[start:stop, daily.columns.get_loc("BB20_Middle")] = middle
            if requested.intersection(("BB20_Upper", "BB20_Lower")):
                std = _rolling_std(values)
                for column, direction in (("BB20_Upper", 1), ("BB20_Lower", -1)):
                    if column in requested:
                        daily.iloc[start:stop, daily.columns.get_loc(column)] = middle + direction * 2 * std


def compute_selected(prepared: pd.DataFrame, features: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return requested daily columns and pivots with v1 numerical semantics.

    Columns and pivot multipliers use ALL_FEATURES order, independent of request
    order. Empty requests are valid; duplicate and unknown names are rejected.
    Inputs still obey the full v1 prepared OHLC/Quality/calendar contract. No
    prepared columns are carried through, and inputs are never mutated.
    definition_metadata() identifies formulas separately from API selection.
    """
    requested = _requests(features)
    prices, valid = _validate(prepared)
    columns = [feature for feature in DAILY_FEATURES if feature in requested]
    daily = pd.DataFrame(np.nan, index=prepared.index, columns=pd.Index(columns), dtype=float)
    ks = tuple(k for feature, k in PIVOT_FEATURES.items() if feature in requested)
    atr: np.ndarray | None = None
    if ks or requested.intersection(("ATR14", "atr14_pct")):
        atr = _atr(prices, valid)
        if "ATR14" in requested:
            daily["ATR14"] = atr
        if "atr14_pct" in requested:
            daily["atr14_pct"] = atr / prices[:, 3]
    convenience = requested.intersection(DAILY_FEATURES[2:])
    if convenience:
        _selected_convenience(daily, prices[:, 3], valid, convenience)
    if ks:
        assert atr is not None  # Every pivot request enters the ATR dependency branch.
        pivots = _pivots(prices, valid, atr, cast(pd.DatetimeIndex, prepared.index), ks)
    else:
        pivots = pd.DataFrame(columns=pd.Index(PIVOT_DTYPES)).astype(PIVOT_DTYPES)
    LOGGER.debug(
        "Computed selected features rows=%d valid=%d requested=%s pivots=%d",
        len(daily),
        int(valid.sum()),
        [name for name in ALL_FEATURES if name in requested],
        len(pivots),
    )
    return daily, pivots

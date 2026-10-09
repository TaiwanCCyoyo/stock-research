"""Price-only components extracted from the legacy 2B/MA candidate.

These flags exclude strategy entry gates, positions, sizing, and broker state.
Missing OHLC resets all history and pending breaks. Flags use float 0/1/NaN.
"""

from __future__ import annotations

import logging
from typing import cast

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
SOURCE_PATH = "tasks/20260814-2b-false-break-structure/candidates/two_b_ma_convergence.py"
OHLC_COLUMNS = ["Open", "High", "Low", "Close"]
LEGACY_SPECS = {
    "F33": {
        "name": "legacy_bottom_2b",
        "family": "recovery",
        "source_method_ids": ["LEGACY-2B"],
        "source_path": SOURCE_PATH,
        "formula": (
            "Low < min prior 20 Low sets pending(level=prior min, expires=5); later non-new-low bar decrements expiry and fires if Close > level before removal"
        ),
        "lookback": 21,
        "defaults": {"swing_lookback": 20, "reclaim_window": 5, "two_b_break_pct": 0.0},
        "version_notes": (
            "v1: detect_bottom_2b component only; new low overrides pending; no same-bar reclaim; "
            "gap resets history and pending; excludes calculate_signal warmup/entry gates"
        ),
    },
    "F34": {
        "name": "legacy_ma_convergence",
        "family": "trend",
        "source_method_ids": ["LEGACY-MA"],
        "source_path": SOURCE_PATH,
        "formula": "(max(SMA5, SMA10, SMA20) - min(SMA5, SMA10, SMA20)) / Close <= 0.02",
        "lookback": 20,
        "defaults": {"windows": [5, 10, 20], "ma_type": "sma", "convergence_pct": 2.0},
        "version_notes": "v1: is_converged SMA component; 20 observations including current; gap resets history",
    },
    "F35": {
        "name": "legacy_convergence_trend_ready",
        "family": "trend",
        "source_method_ids": ["LEGACY-MA"],
        "source_path": SOURCE_PATH,
        "formula": "F34 and Close >= Close.shift(19)",
        "lookback": 20,
        "defaults": {"windows": [5, 10, 20], "ma_type": "sma", "trend_window": 20},
        "version_notes": (
            "v1: convergence plus is_trend_ready SMA price comparison; 20 observations including current; "
            "excludes legacy caller's extra warmup and position gates"
        ),
    },
}


def _segment(frame: pd.DataFrame) -> pd.DataFrame:
    close = cast(pd.Series, frame["Close"])
    means = pd.concat([cast(pd.Series, close.rolling(window).mean()) for window in (5, 10, 20)], axis=1)
    fraction = ((means.max(axis=1) - means.min(axis=1)) / close).where(means.notna().all(axis=1))
    result = pd.DataFrame(index=frame.index)
    result["ma_convergence_fraction"] = fraction
    result["F34"] = (fraction <= 0.02).astype(float).where(fraction.notna())
    result["F35"] = ((result["F34"] == 1) & (close >= close.shift(19))).astype(float).where(fraction.notna())

    lows = frame["Low"].to_numpy(dtype=float)
    closes = close.to_numpy(dtype=float)
    flags = np.full(len(frame), np.nan)
    pending_level: float | None = None
    expires = 0
    for index in range(20, len(frame)):
        prior_low = float(lows[index - 20 : index].min())
        flags[index] = 0.0
        if lows[index] < prior_low:
            pending_level, expires = prior_low, 5
        elif pending_level is not None:
            expires -= 1
            if closes[index] > pending_level:
                flags[index] = 1.0
                pending_level = None
            elif expires <= 0:
                pending_level = None
    result["F33"] = flags
    return result


def compute_legacy_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Return aligned F33/F34/F35 and continuous MA convergence fraction.

    Input is sorted, unique daily OHLC with positive prices and explicit NaN
    gap rows. Every gap starts fresh 20-observation history; F33 additionally
    needs the current bar after 20 prior observations. No input is mutated.
    """
    if not isinstance(frame.index, pd.DatetimeIndex) or not frame.index.is_monotonic_increasing or not frame.index.is_unique:
        raise ValueError("index must be a sorted unique DatetimeIndex")
    data = cast(pd.DataFrame, frame[OHLC_COLUMNS]).astype(float)
    if np.isinf(data.to_numpy()).any() or (data <= 0).any().any():
        raise ValueError("OHLC must be positive; infinity is invalid")
    output = pd.DataFrame(np.nan, index=frame.index, columns=pd.Index(["ma_convergence_fraction", *LEGACY_SPECS]))
    valid = cast(pd.Series, data.notna().all(axis=1))
    groups = (~valid).cumsum()
    LOGGER.debug("Computing legacy atlas components for %d rows; %d OHLC gaps", len(data), (~valid).sum())
    for _, segment in data.loc[valid].groupby(groups.loc[valid], sort=False):
        # Every legacy component requires at least 20 consecutive prices. Keep
        # the preallocated unknowns instead of computing all-NaN short segments.
        if len(segment) < 20:
            continue
        computed = _segment(segment)
        output.loc[segment.index, computed.columns] = computed
    return output

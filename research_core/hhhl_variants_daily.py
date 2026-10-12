"""Pure daily calculations and vectorized bins for approved HHHL variants v1."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.derived_features import compute_features
from research_core.hhhl_variants_features import FEATURES

LOGGER = logging.getLogger(__name__)
OHLC = ("Open", "High", "Low", "Close")


def _dates(frame: pd.DataFrame) -> pd.DatetimeIndex:
    dates = pd.DatetimeIndex(pd.to_datetime(frame["Date"])) if "Date" in frame else pd.DatetimeIndex(frame.index)
    if dates.tz is not None or dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing:
        raise ValueError("common calendar must be unique, sorted, nonmissing and timezone-naive")
    if not dates.equals(cast(Any, dates).normalize()):
        raise ValueError("common calendar must contain midnight dates")
    return dates


def _weekly_signal(dates: pd.DatetimeIndex, close: pd.Series) -> pd.Series:
    """Assign only the previous observed ISO week's completed signal."""
    if not len(dates):
        return pd.Series([], index=close.index, dtype="boolean")
    monday = dates - pd.to_timedelta(cast(Any, dates).dayofweek, unit="D")
    table = pd.DataFrame({"week": monday, "close": close.to_numpy()})
    grouped = table.groupby("week", sort=True)
    weekly = cast(pd.Series, grouped["close"].last())
    valid = grouped["close"].count().eq(grouped.size())
    valid &= weekly.index >= dates[0]
    weekly = cast(pd.Series, weekly.where(valid))
    ma = cast(pd.Series, weekly.rolling(10, min_periods=10).mean())
    known = weekly.rolling(11, min_periods=11).count().eq(11)
    signal = cast(pd.Series, ((weekly > ma) & (ma > ma.shift(1))).astype("boolean"))
    signal = cast(pd.Series, signal.where(known))
    previous = signal.shift(1)
    return pd.Series(previous.reindex(monday).array, index=close.index, dtype="boolean")


def _local_unknown_reasons(
    result: pd.DataFrame, dates: pd.DatetimeIndex, valid: np.ndarray, raw_valid: pd.Series, spread: np.ndarray, median: pd.Series
) -> None:
    """Attach provenance of unknown values without modifying their formulas."""
    positions = np.arange(len(result))
    prior_gap = np.r_[False, np.maximum.accumulate(~valid)[:-1]] if len(valid) else np.array([], dtype=bool)
    windows = {"C": 239, "C2": 259, "C3": 239, "D": 250, "D2": 250, "F": 133, "K": 13}
    for feature_id, first_available in windows.items():
        unknown = ~np.isfinite(result[feature_id].to_numpy(dtype=float, na_value=np.nan))
        reason = np.full(len(result), None, dtype=object)
        reason[unknown] = "warmup_insufficient"
        reason[unknown & (positions >= first_available) & prior_gap] = "warmup_insufficient_after_gap"
        if feature_id != "F":
            reason[unknown & ~valid] = "missing_price"
        else:
            # F observes the previous ATR prefix; a missing current quote is
            # irrelevant when that prefix is already completely observable.
            nonpositive = median.notna().to_numpy() & median.le(0).to_numpy()
            reason[unknown & nonpositive] = "nonpositive_atr_median"
        result[f"{feature_id}_unknown_reason"] = reason
    monday = dates - pd.to_timedelta(cast(Any, dates).dayofweek, unit="D")
    week_codes, _ = pd.factorize(monday, sort=True)
    weekly_gap = pd.Series(~valid).groupby(week_codes).any()
    earlier_week_gap = weekly_gap.cummax().shift(1, fill_value=False)
    prior_week_gap = earlier_week_gap.reindex(week_codes).to_numpy(dtype=bool)
    weekly_unknown = result["C4"].isna().to_numpy()
    weekly_reason = np.full(len(result), None, dtype=object)
    weekly_reason[weekly_unknown] = "warmup_insufficient"
    weekly_reason[weekly_unknown & (week_codes >= 11) & prior_week_gap] = "warmup_insufficient_after_gap"
    result["C4_unknown_reason"] = weekly_reason
    for feature_id, missing, reason_text in (
        ("G", ~np.isfinite(result["G"].to_numpy(dtype=float, na_value=np.nan)), "legacy_vx_unknown"),
        ("K2", ~raw_valid.to_numpy(dtype=bool), "missing_raw_close"),
    ):
        reason = np.full(len(result), None, dtype=object)
        reason[missing] = reason_text
        result[f"{feature_id}_unknown_reason"] = reason
    limit_reason = np.full(len(result), None, dtype=object)
    limit_reason[result["G2_limit"].isna().to_numpy()] = "warmup_insufficient"
    raw_pair_valid = raw_valid & raw_valid.shift(1, fill_value=True)
    limit_reason[~raw_pair_valid.to_numpy(dtype=bool)] = "missing_raw_close"
    result["G2_limit_unknown_reason"] = limit_reason
    position_reason = np.full(len(result), None, dtype=object)
    position_reason[~valid] = "missing_price"
    position_reason[valid & (spread == 0)] = "flat_price_range"
    result["G2_position_unknown_reason"] = position_reason


def calculate_daily_features(raw: pd.DataFrame, adjusted: pd.DataFrame, legacy_vx: np.ndarray, legacy_liquid: np.ndarray) -> pd.DataFrame:
    """Keep calendar gaps; inputs are supplied frames, never loaded or mutated.

    Adjusted OHLC already uses the pinned v4 factors. Legacy vx/liquidity are
    externally supplied frozen semantics; liquidity filtering belongs to K3's
    cross-sectional caller, not these per-stock calculations.
    """
    dates = _dates(raw)
    if not dates.equals(_dates(adjusted)) or len(legacy_vx) != len(raw) or len(legacy_liquid) != len(raw):
        raise ValueError("frames and legacy arrays must share the common-calendar rows")
    if not raw.columns.is_unique or not adjusted.columns.is_unique:
        raise ValueError("duplicate input columns")
    required = set((*OHLC, "VolumeLots"))
    if not required.issubset(raw) or not set(OHLC).issubset(adjusted):
        raise ValueError("raw OHLC/VolumeLots and adjusted OHLC are required")
    prepared = adjusted.loc[:, OHLC].copy()
    prepared.index = dates
    prepared["Quality"] = True
    daily, _ = compute_features(prepared)
    prices = prepared.loc[:, OHLC].to_numpy(dtype=float, na_value=np.nan)
    opening, high, low, closing = prices.T
    valid = np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    valid &= (high >= low) & (opening >= low) & (opening <= high) & (closing >= low) & (closing <= high)
    close = pd.Series(np.where(valid, closing, np.nan), index=raw.index)
    ma20, ma60, ma120 = (pd.Series(daily[f"SMA{n}"].to_numpy(), index=raw.index) for n in (20, 60, 120))
    ma240 = cast(pd.Series, close.rolling(240, min_periods=240).mean())
    atr_pct = cast(pd.Series, pd.Series(daily["atr14_pct"].to_numpy(), index=raw.index).where(valid))
    result = pd.DataFrame(index=raw.index)
    complete = pd.concat([close, ma20, ma60, ma120, ma240], axis=1).notna().all(axis=1)
    count = (close > ma20).astype(int) + (ma20 > ma60).astype(int) + (ma60 > ma120).astype(int) + (ma120 > ma240).astype(int)
    result["C"] = count.where(complete).astype(float)
    slope = cast(pd.Series, ma240 / ma240.shift(20) - 1)
    result["C2"] = slope.where(close.rolling(260, min_periods=260).count().eq(260))
    result["C3"] = close / ma240 - 1
    result["C4"] = _weekly_signal(dates, close)
    previous = close.shift(1)
    result["D"] = close / previous.rolling(250, min_periods=250).max()
    result["D2"] = close / previous.rolling(250, min_periods=250).min()
    median = cast(pd.Series, atr_pct.shift(1).rolling(120, min_periods=120).median())
    result["F"] = (atr_pct.shift(1) / median).where(median > 0)
    result["G"] = np.asarray(legacy_vx, dtype=float)
    raw_close = pd.Series(raw["Close"].to_numpy(dtype=float, na_value=np.nan), index=raw.index)
    raw_valid = pd.Series(np.isfinite(raw_close.to_numpy()) & (raw_close.to_numpy() > 0), index=raw.index)
    raw_close = raw_close.where(raw_valid)
    result["G2_limit"] = ((raw_close / raw_close.shift(1) - 1) >= 0.095).astype("boolean").where(raw_close.notna() & raw_close.shift(1).notna())
    spread = high - low
    result["G2_position"] = pd.Series(((closing - low) / np.where(spread > 0, spread, np.nan)) >= 0.75, index=raw.index, dtype="boolean").where(
        valid & (spread > 0)
    )
    result["K"] = atr_pct
    result["K2"] = raw_close
    result["ret120"] = (close / close.shift(120) - 1).where(close.rolling(121, min_periods=121).count().eq(121))
    volume = pd.Series(raw["VolumeLots"].to_numpy(dtype=float, na_value=np.nan), index=raw.index)
    volume = volume.where(np.isfinite(volume) & (volume >= 0) & raw_valid & valid)
    result["prior_volume20"] = volume.shift(1).rolling(20, min_periods=20).mean()
    result["turnover20"] = (raw_close * volume).shift(1).rolling(20, min_periods=20).mean()
    result["ma20"], result["ma60"], result["atr_pct"] = ma20, ma60, atr_pct
    _local_unknown_reasons(result, dates, valid, raw_valid, spread, median)
    LOGGER.debug("Calculated variants daily rows=%d valid=%d", len(result), int(valid.sum()))
    return result


def _aligned(values: pd.Series, supplied: Any, default: Any) -> pd.Series:
    if supplied is None:
        return pd.Series(default, index=values.index)
    if isinstance(supplied, pd.Series):
        if not supplied.index.equals(values.index):
            raise ValueError("bin argument indices must match values")
        return supplied.copy()
    if np.isscalar(supplied):
        return pd.Series(supplied, index=values.index)
    return pd.Series(supplied, index=values.index)


def bin_values(feature_id: str, values: pd.Series | Sequence[Any], applicable: Any = None, unknown_reason: Any = None) -> pd.DataFrame:
    """Classify one whole column from the approved inventory, without dataclasses.

    C's integer count may be float-backed to represent missingness. Boolean
    features require actual bool values; numerical 0/1 are never bool aliases.
    """
    definition = FEATURES[feature_id]
    column: pd.Series = values.copy() if isinstance(values, pd.Series) else pd.Series(values)
    inferred = pd.api.types.infer_dtype(column, skipna=True)
    if inferred in {"integer", "floating", "mixed-integer-float", "decimal"} and not pd.api.types.is_numeric_dtype(column):
        column = cast(pd.Series, pd.to_numeric(column, errors="raise"))
    allowed = _aligned(column, applicable, True)
    if allowed.isna().any() or not pd.api.types.is_bool_dtype(allowed):
        raise ValueError("applicable must contain nonmissing booleans")
    reasons = _aligned(column, unknown_reason, None)
    explicit = reasons.notna()
    object_reasons = cast(pd.Series, reasons[explicit].astype(object))
    reason_valid = object_reasons.map(lambda value: isinstance(value, str) and bool(value.strip())).to_numpy(dtype=bool)
    if not np.all(reason_valid):
        raise ValueError("unknown_reason must be a nonempty string")
    result = pd.DataFrame(
        {
            f"{feature_id}_bin": pd.Series(None, index=column.index, dtype=object),
            f"{feature_id}_status": "feature_unknown",
            f"{feature_id}_reason": "missing_or_nonfinite",
        },
        index=column.index,
    )
    missing = column.isna()
    numeric_dtype = pd.api.types.is_numeric_dtype(column)
    bool_dtype = pd.api.types.is_bool_dtype(column)
    if numeric_dtype and not bool_dtype:
        missing |= ~np.isfinite(column.to_numpy(dtype=float, na_value=np.nan))
    active = allowed & ~explicit & ~missing
    if feature_id == "I":
        source_unknown = active & column.eq("unknown")
        result.loc[source_unknown, f"{feature_id}_reason"] = "source_market_unknown"
        active &= ~source_unknown
    assigned = pd.Series(False, index=column.index)
    if definition.categories:
        sample = definition.categories[0][1]
        if isinstance(sample, bool):
            valid_type = pd.Series(bool_dtype or inferred == "boolean", index=column.index)
            if not bool_dtype and inferred != "boolean" and not numeric_dtype:
                valid_type = cast(pd.Series, column.astype(object)).map(lambda value: isinstance(value, (bool, np.bool_)))
        elif isinstance(sample, int):
            valid_type = pd.Series(numeric_dtype and not bool_dtype, index=column.index)
        else:
            valid_type = pd.Series(inferred == "string", index=column.index)
            if inferred != "string" and not numeric_dtype:
                valid_type = cast(pd.Series, column.astype(object)).map(lambda value: isinstance(value, str))
        for bin_id, expected in definition.categories:
            matched = active & valid_type & column.eq(expected).fillna(False)
            result.loc[matched, f"{feature_id}_bin"] = bin_id
            assigned |= matched
    else:
        if bool_dtype or (active.any() and not numeric_dtype):
            raise ValueError(f"numeric values required for {feature_id}")
        numbers = column.to_numpy(dtype=float, na_value=np.nan)
        if definition.discrete_count and np.any(active.to_numpy() & ((numbers < 0) | (numbers != np.floor(numbers)))):
            raise ValueError(f"nonnegative integer count required for {feature_id}")
        for interval in definition.numeric_bins:
            matched = active.copy()
            if interval.lower is not None:
                matched &= column.ge(interval.lower) if interval.lower_inclusive else column.gt(interval.lower)
            if interval.upper is not None:
                matched &= column.le(interval.upper) if interval.upper_inclusive else column.lt(interval.upper)
            result.loc[matched, f"{feature_id}_bin"] = interval.bin_id
            assigned |= matched
    if (active & ~assigned).any():
        raise ValueError(f"unexpected values for {feature_id}")
    result.loc[assigned, f"{feature_id}_status"] = "known"
    result.loc[assigned, f"{feature_id}_reason"] = None
    result.loc[allowed & explicit, f"{feature_id}_reason"] = reasons[allowed & explicit]
    result.loc[~allowed, f"{feature_id}_status"] = "not_applicable"
    result.loc[~allowed, f"{feature_id}_reason"] = "outside_feature_cohort"
    return result


def bin_columns(values: pd.DataFrame) -> pd.DataFrame:
    """Bin every inventory column; absent columns are explicitly unknown.

    Optional '<ID>_applicable' and '<ID>_unknown_reason' columns carry caller
    cohort applicability and source/warmup reasons without changing formulas.
    """
    pieces = []
    for feature_id in FEATURES:
        column = cast(pd.Series, values[feature_id]) if feature_id in values else pd.Series(np.nan, index=values.index)
        pieces.append(bin_values(feature_id, column, values.get(f"{feature_id}_applicable"), values.get(f"{feature_id}_unknown_reason")))
    return pd.concat(pieces, axis=1)

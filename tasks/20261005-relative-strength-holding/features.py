"""Causal rolling policy inputs over caller-bound prices and daily membership.

Signal prices must already have causal source adjustment. This builder infers
neither adjustment factors nor PIT membership, execution prices or outcomes.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import date, datetime
from typing import cast

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
OHLC = ("Open", "High", "Low", "Close")
LIQUIDITY_THRESHOLD_TWD = 20_000_000


class FeatureError(ValueError):
    """Caller inputs cannot establish the declared causal feature panel."""


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    return cast(pd.Series, frame[name])


def _numeric(frame: pd.DataFrame, name: str) -> pd.Series:
    values = _column(frame, name)
    if not values.dropna().empty and (not pd.api.types.is_numeric_dtype(values) or pd.api.types.is_bool_dtype(values)):
        raise FeatureError(f"{name} must be numeric, not malformed text or booleans")
    numeric = cast(pd.Series, pd.to_numeric(values, errors="raise")).astype(float)
    if not np.isfinite(numeric.dropna().to_numpy()).all():
        raise FeatureError(f"{name} must be finite or genuinely missing")
    return numeric


def _prices(frame: pd.DataFrame, name: str) -> tuple[pd.DataFrame, pd.Series]:
    result = frame.copy()
    for column in OHLC:
        values = _numeric(result, column)
        if values.dropna().le(0).any():
            raise FeatureError(f"{name} {column} must be positive")
        result[column] = values
    high, low = _column(result, "High"), _column(result, "Low")
    if (
        high.lt(low) | high.lt(_column(result, "Open")) | high.lt(_column(result, "Close")) | low.gt(_column(result, "Open")) | low.gt(_column(result, "Close"))
    ).any():
        raise FeatureError(f"{name} has inconsistent OHLC")
    usable = cast(pd.Series, cast(pd.DataFrame, result[list(OHLC)]).notna().all(axis=1))
    return result, usable


def _keys(frame: pd.DataFrame, name: str, calendar: tuple[date, ...]) -> pd.DataFrame:
    result = frame.copy()
    codes = _column(result, "Code")
    if codes.isna().any() or pd.api.types.infer_dtype(codes.dropna()) not in ("string", "unicode", "empty") or codes.astype(str).str.strip().eq("").any():
        raise FeatureError(f"{name} requires nonempty string Code")
    result["Code"] = codes.astype(str)
    values = _column(result, "Date")
    try:
        dates = cast(pd.Series, pd.to_datetime(values, errors="raise"))
    except (ValueError, TypeError) as error:
        raise FeatureError(f"{name} requires valid Date") from error
    if dates.isna().any() or dates.dt.tz is not None or not dates.eq(dates.dt.normalize()).all():
        raise FeatureError(f"{name} requires nonmissing timezone-naive calendar Date")
    if pd.api.types.infer_dtype(values.dropna()) in ("string", "unicode") and not values.eq(dates.dt.strftime("%Y-%m-%d")).all():
        raise FeatureError(f"{name} requires unambiguous ISO Date")
    result["Date"] = dates
    if result.duplicated(["Code", "Date"]).any():
        raise FeatureError(f"{name} has duplicate Code/Date keys")
    if not dates.isin(pd.DatetimeIndex(calendar)).all():
        raise FeatureError(f"{name} rows outside explicit calendar scope")
    return result.sort_values(["Code", "Date"]).reset_index(drop=True)


def _calendar(calendar: tuple[date, ...], universe: Mapping[date, frozenset[str]]) -> None:
    if not isinstance(calendar, tuple) or any(not isinstance(day, date) or isinstance(day, datetime) for day in calendar):
        raise FeatureError("calendar must be a tuple of date-only values")
    if any(left >= right for left, right in zip(calendar, calendar[1:])):
        raise FeatureError("calendar must be unique and strictly increasing")
    if not isinstance(universe, Mapping) or set(universe) != set(calendar):
        raise FeatureError("universe must cover every calendar date exactly")
    for day, codes in universe.items():
        if (
            not isinstance(day, date)
            or isinstance(day, datetime)
            or not isinstance(codes, frozenset)
            or any(not isinstance(code, str) or not code.strip() for code in codes)
        ):
            raise FeatureError("universe requires date-only keys and frozensets of nonempty codes")


def _availability(raw: pd.DataFrame) -> pd.Series:
    try:
        values = cast(pd.Series, pd.to_datetime(_column(raw, "available_at"), errors="raise"))
    except (ValueError, TypeError) as error:
        raise FeatureError("available_at must be aware +08:00 timestamps") from error
    if values.isna().any() or not isinstance(values.dtype, pd.DatetimeTZDtype):
        raise FeatureError("available_at must be nonmissing aware +08:00 timestamps")
    # A timezone's offset may vary historically, so test each distinct date's
    # offset rather than accepting its name as availability evidence.
    offsets = values.dt.strftime("%z")
    if not offsets.eq("+0800").all():
        raise FeatureError("available_at must have +08:00 offset")
    local = values.dt.tz_localize(None)
    dates = _column(raw, "Date")
    if not local.dt.normalize().eq(dates).all() or local.gt(dates + pd.Timedelta(hours=20)).any():
        raise FeatureError("available_at must be on row date and no later than 20:00")
    return values


def build_policy_panel(
    raw: pd.DataFrame,
    signal: pd.DataFrame,
    *,
    calendar: tuple[date, ...],
    universe: Mapping[date, frozenset[str]],
    source_id: str,
    raw_volume_unit: str = "shares",
) -> pd.DataFrame:
    """Build only original stock/date rows, using uncompressed calendar history.

    Sixty usable closes admit ordinary members to the rank population; ret60
    itself needs 61 contiguous closes. Average-tie percentiles precede the
    twenty-session raw-price-times-share-volume median liquidity admission.
    A membership loss removes today's ranking, not historical exit averages.
    ``source_id`` retains raw row provenance; ``panel_source_id`` identifies
    the caller's binding of the raw and supplied causal signal inputs.
    """
    _calendar(calendar, universe)
    if not isinstance(source_id, str) or not source_id.strip():
        raise FeatureError("panel source_id must be nonempty")
    if raw_volume_unit != "shares":
        raise FeatureError("raw Volume unit must be shares")
    raw_required = {"Code", "Date", "Market", "Volume", "available_at", "source_id", *OHLC}
    signal_required = {"Code", "Date", *OHLC}
    if not raw_required.issubset(raw.columns) or not signal_required.issubset(signal.columns):
        raise FeatureError("missing raw/signal contract columns")
    raw = _keys(cast(pd.DataFrame, raw[sorted(raw_required)]), "raw", calendar)
    signal = _keys(cast(pd.DataFrame, signal[sorted(signal_required)]), "signal", calendar)
    if not cast(pd.DataFrame, raw[["Code", "Date"]]).equals(cast(pd.DataFrame, signal[["Code", "Date"]])):
        raise FeatureError("raw/signal Code/Date keys must match one-to-one")
    raw, raw_usable = _prices(raw, "raw")
    signal, signal_usable = _prices(signal, "signal")
    if not _column(raw, "Market").isin(["TWSE", "TPEX"]).all():
        raise FeatureError("Market must be TWSE or TPEX")
    ids = _column(raw, "source_id")
    if ids.isna().any() or pd.api.types.infer_dtype(ids.dropna()) not in ("string", "unicode", "empty") or ids.astype(str).str.strip().eq("").any():
        raise FeatureError("raw source_id must be nonempty strings")
    available = _availability(raw)
    volume = _numeric(raw, "Volume")
    if volume.dropna().lt(0).any():
        raise FeatureError("raw Volume must be nonnegative")
    with np.errstate(over="ignore", invalid="ignore"):
        traded_value = _column(raw, "Close") * volume
    if not np.isfinite(traded_value.dropna().to_numpy()).all():
        raise FeatureError("raw traded value must be finite or missing")
    panel = cast(pd.DataFrame, raw[["Market", "Code", "Date"]]).copy()
    panel["signal_close"] = _column(signal, "Close")
    panel["usable"] = raw_usable & signal_usable
    panel["traded_value"] = traded_value
    panel["available_at"] = available
    panel["source_id"] = ids
    panel["panel_source_id"] = source_id
    pieces = []
    dates = pd.DatetimeIndex(calendar)
    for _code, group in panel.groupby("Code", observed=True, sort=False):
        original_dates = _column(group, "Date")
        history = group.set_index("Date").reindex(dates)
        usable = _column(history, "usable").eq(True)
        close = _column(history, "signal_close").where(usable)
        streak = usable.astype(int).groupby((~usable).cumsum()).cumsum()
        history["consecutive_usable"] = streak
        history["ma20"] = close.rolling(20, min_periods=20).mean()
        history["ma60"] = close.rolling(60, min_periods=60).mean()
        history["ret60"] = (close / close.shift(60) - 1).where(streak.ge(61))
        history["liquidity_twd"] = _column(history, "traded_value").rolling(20, min_periods=20).median()
        pieces.append(history.loc[pd.DatetimeIndex(original_dates)].rename_axis("Date").reset_index())
    if pieces:
        result = pd.concat(pieces, ignore_index=True).sort_values(["Code", "Date"]).reset_index(drop=True)
    else:
        result = panel.copy()
        result["consecutive_usable"] = pd.Series(dtype=int)
        for column in ("ma20", "ma60", "ret60", "liquidity_twd"):
            result[column] = pd.Series(dtype=float)
    for column in ("ma20", "ma60", "ret60", "liquidity_twd"):
        if not np.isfinite(_column(result, column).dropna().to_numpy()).all():
            raise FeatureError(f"derived {column} must be finite or missing")
    # Each day's vectorized membership lookup avoids materializing millions
    # of date/code tuples, and never consults a future day's admissions.
    ordinary = pd.Series(False, index=result.index)
    codes = _column(result, "Code")
    for day, indices in result.groupby("Date", observed=True, sort=False).indices.items():
        if not isinstance(day, pd.Timestamp):
            raise FeatureError("validated Date grouping requires Timestamp keys")
        ordinary.iloc[indices] = codes.iloc[indices].isin(universe[day.date()])
    result["rank_eligible"] = ordinary & _column(result, "consecutive_usable").ge(60)
    ranked = _column(result, "ret60").where(_column(result, "rank_eligible"))
    result["rs60"] = ranked.groupby(_column(result, "Date")).rank(method="average", pct=True)
    liquidity = _column(result, "liquidity_twd")
    eligible = _column(result, "rank_eligible") & _column(result, "ret60").notna() & liquidity.ge(LIQUIDITY_THRESHOLD_TWD)
    result["eligible"] = eligible.astype(bool)
    result["eligibility_reason"] = np.select(
        [
            ~_column(result, "usable").astype(bool),
            ~ordinary,
            _column(result, "consecutive_usable").lt(60),
            _column(result, "ret60").isna(),
            liquidity.isna(),
            liquidity.lt(LIQUIDITY_THRESHOLD_TWD),
        ],
        [
            "missing_ohlc",
            "not_current_ordinary_member",
            "insufficient_consecutive_closes",
            "ret60_requires_61_closes",
            "missing_liquidity",
            "liquidity_below_threshold",
        ],
        default="eligible",
    )
    result = result.drop(columns=["usable", "traded_value"])
    columns = [
        "Market",
        "Code",
        "Date",
        "signal_close",
        "ma20",
        "ma60",
        "ret60",
        "rs60",
        "consecutive_usable",
        "rank_eligible",
        "liquidity_twd",
        "eligible",
        "eligibility_reason",
        "available_at",
        "source_id",
        "panel_source_id",
    ]
    LOGGER.info(
        "Built policy panel rows=%d codes=%d sessions=%d ranked=%d eligible=%d",
        len(result),
        _column(result, "Code").nunique(),
        len(calendar),
        _column(result, "rs60").notna().sum(),
        eligible.sum(),
    )
    return cast(pd.DataFrame, result[columns])

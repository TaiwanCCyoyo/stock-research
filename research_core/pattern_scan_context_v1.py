"""Pure supplied-0050 context on an explicitly complete research calendar."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import cast

import numpy as np
import pandas as pd

from research_core.market_context import compute_context_rows, definition

LOGGER = logging.getLogger(__name__)


def build_context(stock_frame: pd.DataFrame, benchmark_frame: pd.DataFrame, expected_security_ids: Sequence[str]) -> pd.DataFrame:
    """Return causal MKT and separate hindsight holding-context vectors.

    stock_frame requires security_id/t0/calendar_index, every declared ordinary
    stock and every common session, including padded unavailable observations.
    benchmark_frame supplies independent TW:0050 adjusted Close and boolean
    Quality on that exact DatetimeIndex. It must retain missing/raw-span padding;
    no ordinary-stock aggregation substitutes for the benchmark. Its source,
    factors and vintage are pinned externally by the caller.

    MKT uses only [t-20,t]; retrospective_state uses [t-10,t+10] and must never
    be an entry condition. Unknown coverage remains unknown, never mixed.
    """
    if isinstance(expected_security_ids, str):
        raise ValueError("expected_security_ids must be an explicit stock sequence")
    expected = tuple(expected_security_ids)
    if not expected or len(set(expected)) != len(expected) or any(not isinstance(value, str) or not value.strip() for value in expected):
        raise ValueError("expected stocks must be unique nonblank identities")
    if not stock_frame.columns.is_unique or not {"security_id", "t0", "calendar_index"}.issubset(stock_frame):
        raise ValueError("stock frame requires complete-grid identity columns")
    if not isinstance(benchmark_frame.index, pd.DatetimeIndex) or not benchmark_frame.columns.is_unique or not {"Close", "Quality"}.issubset(benchmark_frame):
        raise ValueError("benchmark requires Close/Quality and common DatetimeIndex")
    calendar = cast(pd.DatetimeIndex, benchmark_frame.index)
    if (
        not len(calendar)
        or calendar.tz is not None
        or calendar.hasnans
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
        or any(cast(pd.Timestamp, day) != cast(pd.Timestamp, day).normalize() for day in calendar)
    ):
        raise ValueError("common calendar must be nonempty sorted unique timezone-naive midnight dates")
    dates = calendar.strftime("%Y-%m-%d").tolist()
    if stock_frame.security_id.isna().any() or set(stock_frame.security_id) != set(expected):
        raise ValueError("stock pool does not match the explicit included universe")
    positions = cast(pd.Series, stock_frame["calendar_index"])
    if not pd.api.types.is_integer_dtype(positions) or pd.api.types.is_bool_dtype(positions) or positions.isna().any():
        raise ValueError("calendar_index must be integer")
    if stock_frame.duplicated(["security_id", "calendar_index"]).any() or len(stock_frame) != len(expected) * len(calendar):
        raise ValueError("stock frame must retain the complete unique stock/session grid")
    if positions.lt(0).any() or positions.ge(len(calendar)).any():
        raise ValueError("stock calendar positions do not match benchmark")
    supplied_dates = cast(pd.Series, stock_frame["t0"])
    expected_dates = np.asarray(dates, dtype=object)[positions.to_numpy(dtype=int)]
    if not supplied_dates.eq(expected_dates).all():
        raise ValueError("stock t0 requires canonical dates matching the benchmark calendar")
    if "security_id" in benchmark_frame and not cast(pd.Series, benchmark_frame["security_id"]).eq("TW:0050").all():
        raise ValueError("benchmark identity must be TW:0050")
    close = cast(pd.Series, benchmark_frame["Close"])
    quality = cast(pd.Series, benchmark_frame["Quality"])
    if not pd.api.types.is_numeric_dtype(close) or pd.api.types.is_bool_dtype(close) or not pd.api.types.is_bool_dtype(quality):
        raise ValueError("benchmark Close must be numeric and Quality boolean")
    numeric = close.to_numpy(dtype=float, na_value=np.nan)
    valid = quality.eq(True).fillna(False).to_numpy(dtype=bool) & np.isfinite(numeric) & (numeric > 0)
    closes = [float(value) if known else None for value, known in zip(numeric, valid)]
    past = compute_context_rows(dates, closes, layer="past_only")
    hindsight = compute_context_rows(dates, closes, layer="retrospective")
    result = pd.DataFrame({
        "Date": calendar,
        "calendar_index": np.arange(len(calendar)),
        "MKT": [row["state"] for row in past],
        "MKT_unknown_reason": [row["missing_reason"] for row in past],
        "MKT_information_cutoff": [row["information_cutoff"] for row in past],
        "MKT_window_return": [row["window_return"] for row in past],
        "MKT_window_range": [row["window_range"] for row in past],
        "MKT_event": [row["event"] for row in past],
        "retrospective_state": [row["state"] for row in hindsight],
        "retrospective_unknown_reason": [row["missing_reason"] for row in hindsight],
        "retrospective_information_cutoff": [row["information_cutoff"] for row in hindsight],
        "retrospective_window_return": [row["window_return"] for row in hindsight],
        "retrospective_window_range": [row["window_range"] for row in hindsight],
        "retrospective_event": [row["event"] for row in hindsight],
    })
    usable = np.flatnonzero(valid)
    result.attrs["coverage"] = {
        "security_id": "TW:0050",
        "ordinary_security_n": len(expected),
        "calendar_n": len(calendar),
        "calendar_start": dates[0],
        "calendar_end": dates[-1],
        "usable_benchmark_n": int(valid.sum()),
        "first_usable_benchmark_date": dates[int(usable[0])] if len(usable) else None,
        "last_usable_benchmark_date": dates[int(usable[-1])] if len(usable) else None,
        "past_only_unknown_n": sum(row["state"] == "unknown" for row in past),
        "retrospective_unknown_n": sum(row["state"] == "unknown" for row in hindsight),
        "historical_availability_certified": False,
    }
    result.attrs["definition"] = definition()
    LOGGER.debug("Built supplied 0050 context stocks=%d sessions=%d usable_benchmark=%d", len(expected), len(calendar), int(valid.sum()))
    return result

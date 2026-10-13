"""Bounded checkpoint kernel with its own numerical identity.

Rolling outputs reuse v1's formulas on independent per-period OHLC windows.
The largest requested period bounds the buffer, while each SMA uses only its
own period and all BB20 columns use 20 rows, independent of other requests.
Restarting pandas rolling accumulation can change last bits relative to full-history v1;
v2 full and chunk computation use this same kernel and are exactly identical.
EMA/ATR/pivots carry sufficient state rather than replaying old calendar rows.
Checkpoints are JSON values; their digest detects corruption, not authenticity.
Arithmetic overflow fails closed without returning a new checkpoint. None is
reserved for reset/warmup values, never a replacement for computed infinity.
"""

from __future__ import annotations

import copy
import logging
import math
from collections.abc import Iterable
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core import derived_features_selective_v1 as v1
from research_core.artifact_store import object_digest

DEFINITION_VERSION = "derived-features-checkpoint.v2"
ALL_FEATURES = v1.ALL_FEATURES
LOGGER = logging.getLogger(__name__)


def definition_metadata() -> dict[str, Any]:
    metadata = v1.definition_metadata()
    metadata["version"] = DEFINITION_VERSION
    metadata["numerical_definition_version"] = DEFINITION_VERSION
    metadata["rolling_execution"] = (
        "For each valid new row, compute_selected v1 evaluates each requested "
        "SMA_n on its own last n valid OHLC rows (maximum 120 per period), and "
        "requested BB20 columns together on the last 20 rows. The shared buffer "
        "holds only the largest requested period. Each column is independent "
        "of the requested feature set. Bounded-window pandas accumulation may "
        "differ in last bits from full-history v1. Full v2 and chunked v2 share "
        "the same kernel; total rolling work per row is the sum of requested "
        "SMA periods plus 20 if any BB20 column is requested."
    )
    metadata["checkpoint"] = (
        "JSON state with digest, strict calendar append and fixed feature set; "
        "adding a feature requires initializing its entire prefix under v2. "
        "Do not concatenate v1 outputs with v2 outputs. Arithmetic overflow "
        "raises without returning a checkpoint; None means reset/warmup only."
    )
    return metadata


def _configuration(names: list[str]) -> tuple[list[str], int, list[int], bool, list[str]]:
    rolling = [name for name in names if name.startswith("SMA") or name in v1.BB_COLUMNS]
    periods = [int(name[3:]) if name.startswith("SMA") else 20 for name in rolling]
    ema = [n for n in v1.EMA_PERIODS if f"EMA{n}" in names]
    pivots = [name for name in v1.PIVOT_FEATURES if name in names]
    needs_atr = bool(pivots or set(names).intersection(("ATR14", "atr14_pct")))
    return rolling, max(periods, default=0), ema, needs_atr, pivots


def _reset(body: dict[str, Any], ema_periods: list[int], pivot_names: list[str]) -> None:
    body["valid_run_rows"] = 0
    body["rolling_window"] = []
    body["atr"] = {"count": 0, "sum_tr": 0.0, "previous_close": None, "previous_atr": None}
    body["ema"] = {str(n): {"seed_values": [], "previous_ema": None} for n in ema_periods}
    body["pivots"] = {name: {"mode": 0, "extreme_index": None, "extreme_date": None, "price": None} for name in pivot_names}


def _keys(value: Any, expected: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("checkpoint object fields are invalid")


def _integer(value: Any, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("checkpoint integer/count is invalid")


def _finite(value: Any, *, nullable: bool = False, positive: bool = False) -> None:
    if value is None and nullable:
        return
    if value is None or type(value) not in (int, float):
        raise ValueError("checkpoint numerical value must be finite")
    number = cast(float, value)
    try:
        finite = math.isfinite(number)
    except OverflowError:
        finite = False
    if not finite or (positive and number <= 0):
        raise ValueError("checkpoint numerical value must be finite")


def _date(value: Any) -> pd.Timestamp:
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError("checkpoint date is invalid")
    try:
        day = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise ValueError("checkpoint date is invalid") from error
    if not isinstance(day, pd.Timestamp):
        raise ValueError("checkpoint date must be a timezone-naive midnight date")
    if day.tz is not None or day != day.normalize() or day.strftime("%Y-%m-%d") != value:
        raise ValueError("checkpoint date must be a timezone-naive midnight date")
    return day


def _restore(state: dict[str, Any], names: list[str]) -> dict[str, Any]:
    _keys(state, {"version", "features", "row_count", "calendar_last_date", "valid_run_rows", "rolling_window", "atr", "ema", "pivots", "state_digest"})
    if state["version"] != DEFINITION_VERSION or state["features"] != names:
        raise ValueError("checkpoint version or feature configuration differs")
    if not isinstance(state["features"], list) or not isinstance(state["state_digest"], str):
        raise ValueError("checkpoint metadata types are invalid")
    row_count = state["row_count"]
    _integer(row_count, 0, 2**63 - 1)
    run = state["valid_run_rows"]
    _integer(run, 0, row_count)
    last = None if row_count == 0 else _date(state["calendar_last_date"])
    if row_count == 0 and state["calendar_last_date"] is not None:
        raise ValueError("empty checkpoint must have no calendar date")
    _, window_size, ema_periods, needs_atr, pivot_names = _configuration(names)
    window = state["rolling_window"]
    if not isinstance(window, list) or len(window) != min(run, window_size):
        raise ValueError("checkpoint rolling window length is inconsistent")
    previous_date = None
    for item in window:
        _keys(item, {"date", "ohlc"})
        day = _date(item["date"])
        if last is None or day > last or (previous_date is not None and day <= previous_date):
            raise ValueError("checkpoint rolling dates are inconsistent")
        previous_date = day
        prices = item["ohlc"]
        if not isinstance(prices, list) or len(prices) != 4:
            raise ValueError("checkpoint OHLC window is invalid")
        for price in prices:
            _finite(price, positive=True)
        opening, high, low, close = prices
        if not low <= opening <= high or not low <= close <= high:
            raise ValueError("checkpoint OHLC is inconsistent")
    if window and previous_date != last:
        raise ValueError("checkpoint rolling window does not end at last date")
    atr = state["atr"]
    _keys(atr, {"count", "sum_tr", "previous_close", "previous_atr"})
    expected_count = run if needs_atr else 0
    _integer(atr["count"], expected_count, expected_count)
    _finite(atr["sum_tr"])
    if atr["sum_tr"] < 0:
        raise ValueError("checkpoint TR seed is negative")
    _finite(atr["previous_close"], nullable=expected_count == 0, positive=True)
    _finite(atr["previous_atr"], nullable=expected_count < 14)
    if expected_count == 0 and (atr["sum_tr"] != 0 or atr["previous_close"] is not None):
        raise ValueError("checkpoint reset ATR state is inconsistent")
    if expected_count < 14 and atr["previous_atr"] is not None:
        raise ValueError("checkpoint ATR is present before seeding")
    if atr["previous_atr"] is not None and atr["previous_atr"] < 0:
        raise ValueError("checkpoint ATR is negative")
    _keys(state["ema"], {str(n) for n in ema_periods})
    for n in ema_periods:
        ema = state["ema"][str(n)]
        _keys(ema, {"seed_values", "previous_ema"})
        seed = ema["seed_values"]
        if not isinstance(seed, list) or len(seed) != min(run, n):
            raise ValueError("checkpoint EMA seed length is inconsistent")
        for value in seed:
            _finite(value, positive=True)
        _finite(ema["previous_ema"], nullable=run < n, positive=True)
        if run < n and ema["previous_ema"] is not None:
            raise ValueError("checkpoint EMA is present before seeding")
    _keys(state["pivots"], set(pivot_names))
    for name in pivot_names:
        pivot = state["pivots"][name]
        _keys(pivot, {"mode", "extreme_index", "extreme_date", "price"})
        _integer(pivot["mode"], -1, 1)
        if pivot["mode"] == 0:
            if any(pivot[key] is not None for key in ("extreme_index", "extreme_date", "price")):
                raise ValueError("checkpoint reset pivot is inconsistent")
        else:
            if run < 14 or last is None:
                raise ValueError("checkpoint active pivot lacks ATR context")
            _integer(pivot["extreme_index"], row_count - run + 13, row_count - 1)
            if _date(pivot["extreme_date"]) > last:
                raise ValueError("checkpoint pivot extreme date is in the future")
            _finite(pivot["price"], positive=True)
    body = {key: value for key, value in state.items() if key != "state_digest"}
    if object_digest(body) != state["state_digest"]:
        raise ValueError("checkpoint digest mismatch")
    return copy.deepcopy(body)


def _computed_number(value: float, feature: str) -> float:
    if not np.isfinite(value):
        raise ArithmeticError(f"nonfinite computation for {feature}; no checkpoint returned")
    return float(value)


def _atr_step(atr: dict[str, Any], high: float, low: float, close: float) -> float:
    count = atr["count"]
    tr = high - low if count == 0 else max(high - low, abs(high - atr["previous_close"]), abs(low - atr["previous_close"]))
    count += 1
    previous = np.nan if atr["previous_atr"] is None else atr["previous_atr"]
    if count <= 14:
        atr["sum_tr"] = _computed_number(atr["sum_tr"] + tr, "ATR14 seed")
        if count == 14:
            previous = atr["sum_tr"] / 14
    else:
        previous = (13 * previous + tr) / 14
    available = _computed_number(previous, "ATR14") if count >= 14 else None
    atr.update(count=count, previous_close=close, previous_atr=available)
    return float(previous)


def _ema_step(ema: dict[str, Any], close: float, n: int) -> float:
    seed = ema["seed_values"]
    if len(seed) < n:
        seed.append(close)
        value = float(pd.Series(seed).mean()) if len(seed) == n else np.nan
    else:
        previous = np.nan if ema["previous_ema"] is None else ema["previous_ema"]
        alpha = 2 / (n + 1)
        value = alpha * close + (1 - alpha) * previous
    ema["previous_ema"] = _computed_number(value, f"EMA{n}") if len(seed) == n else None
    return float(value)


def _pivot_step(pivot: dict[str, Any], k: float, high: float, low: float, atr: float, index: int, date: str) -> dict[str, Any] | None:
    if not np.isfinite(atr) or atr <= 0:
        return None
    threshold = _computed_number(k * atr, "pivot threshold")
    mode = pivot["mode"]
    record = None
    if mode == 0:
        mode = 1
    elif (mode == 1 and high >= pivot["price"]) or (mode == -1 and low <= pivot["price"]):
        pass
    elif (mode == 1 and pivot["price"] - low >= threshold) or (mode == -1 and high - pivot["price"] >= threshold):
        record = {
            "k": k,
            "kind": "high" if mode == 1 else "low",
            "extreme_index": pivot["extreme_index"],
            "confirmation_index": index,
            "extreme_date": pd.Timestamp(pivot["extreme_date"]),
            "confirmed_at": pd.Timestamp(date),
            "price": pivot["price"],
        }
        mode = -mode
    else:
        return None
    pivot.update(mode=mode, extreme_index=index, extreme_date=date, price=high if mode == 1 else low)
    return record


def compute_selected_chunk(
    prepared_new: pd.DataFrame,
    features: Iterable[str],
    *,
    state: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Process new rows plus at most 120 warm rows per requested rolling period.

    State is copied and validated, never mutated. Output pivot indices remain
    global, and only confirmations in this chunk are emitted. Features cannot
    change midstream; initialize a new v2 prefix for a different configuration.
    """
    requested = v1._requests(features)
    names = [name for name in ALL_FEATURES if name in requested]
    prices, valid = v1._validate(prepared_new)
    rolling, window_size, ema_periods, needs_atr, pivot_names = _configuration(names)
    if state is None:
        body: dict[str, Any] = {"version": DEFINITION_VERSION, "features": names, "row_count": 0, "calendar_last_date": None}
        _reset(body, ema_periods, pivot_names)
    else:
        body = _restore(state, names)
    if len(prepared_new) and body["calendar_last_date"] is not None and prepared_new.index[0] <= _date(body["calendar_last_date"]):
        raise ValueError("checkpoint calendar requires strictly later new dates")
    columns = [name for name in v1.DAILY_FEATURES if name in requested]
    daily = pd.DataFrame(np.nan, index=prepared_new.index, columns=pd.Index(columns), dtype=float)
    records: list[dict[str, Any]] = []
    for local_index, row in enumerate(prices):
        date = cast(pd.Timestamp, prepared_new.index[local_index]).strftime("%Y-%m-%d")
        global_index = body["row_count"]
        body["row_count"] += 1
        body["calendar_last_date"] = date
        if not valid[local_index]:
            _reset(body, ema_periods, pivot_names)
            continue
        body["valid_run_rows"] += 1
        opening, high, low, close = (float(value) for value in row)
        if rolling:
            window = body["rolling_window"]
            window.append({"date": date, "ohlc": [opening, high, low, close]})
            del window[: max(0, len(window) - window_size)]
            warm = pd.DataFrame([item["ohlc"] for item in window], columns=pd.Index(v1.OHLC), index=pd.DatetimeIndex([item["date"] for item in window]))
            warm["Quality"] = True
            groups = [(int(name[3:]), [name]) for name in rolling if name.startswith("SMA")]
            bb_names = [name for name in rolling if name in v1.BB_COLUMNS]
            if bb_names:
                groups.append((20, bb_names))
            for period, group_names in groups:
                warm_daily, _ = v1.compute_selected(warm.iloc[-period:], group_names)
                for name in group_names:
                    value = warm_daily[name].iloc[-1]
                    if len(window) >= period:
                        value = _computed_number(value, name)
                    daily.iat[local_index, daily.columns.get_loc(name)] = value
        atr = _atr_step(body["atr"], high, low, close) if needs_atr else np.nan
        if "ATR14" in requested:
            daily.iat[local_index, daily.columns.get_loc("ATR14")] = atr
        if "atr14_pct" in requested:
            value = _computed_number(atr / close, "atr14_pct") if body["atr"]["count"] >= 14 else np.nan
            daily.iat[local_index, daily.columns.get_loc("atr14_pct")] = value
        for n in ema_periods:
            daily.iat[local_index, daily.columns.get_loc(f"EMA{n}")] = _ema_step(body["ema"][str(n)], close, n)
        for name in pivot_names:
            record = _pivot_step(body["pivots"][name], v1.PIVOT_FEATURES[name], high, low, atr, global_index, date)
            if record is not None:
                records.append(record)
    pivots = pd.DataFrame(records, columns=pd.Index(v1.PIVOT_DTYPES)).astype(v1.PIVOT_DTYPES)
    pivots = pivots.sort_values(["k", "confirmation_index"], kind="stable").reset_index(drop=True)
    next_state = {**body, "state_digest": object_digest(body)}
    LOGGER.debug(
        "Computed v2 chunk rows=%d valid=%d global_rows=%d warm_bound=%d features=%s pivots=%d",
        len(daily),
        int(valid.sum()),
        body["row_count"],
        window_size,
        names,
        len(pivots),
    )
    return daily, pivots, next_state


def compute_selected_full(prepared: pd.DataFrame, features: Iterable[str]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Initialize a full v2 stream through the exact same checkpoint kernel."""
    return compute_selected_chunk(prepared, features, state=None)

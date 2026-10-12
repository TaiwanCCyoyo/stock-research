"""Pattern-only values from supplied frozen events and adjusted price arrays."""

from __future__ import annotations

import json
import logging
from numbers import Integral, Real
from typing import Any, cast

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)
VALUE_COLUMNS = ("A", "B", "B2", "E", "E2", "E3", "E4_cat", "E4_big", "G")
REASON_FEATURES = ("A", "B", "B2", "E2")
REQUIRED_COLUMNS = ("calendar_index", "restart_date", "Z2", "hz_top", "bonus_levels", "pivot_sequence", "cat", "big_hhhl", "vx", "has_old", "has_recent_far")


def _positive(value: Any) -> bool:
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        return False
    number = float(value)
    return bool(np.isfinite(number)) and number > 0


def _date(value: Any, name: str) -> pd.Timestamp:
    try:
        day = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not isinstance(day, pd.Timestamp) or day.tzinfo is not None or day != day.normalize():
        raise ValueError(f"{name} requires a nonmissing timezone-naive midnight date")
    return day


def _json_list(value: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a JSON string")
    try:
        entries = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid {name} JSON") from exc
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ValueError(f"{name} must contain a list of objects")
    return entries


def pattern_feature_values(events: pd.DataFrame, calendar: pd.DatetimeIndex, adjusted_low: np.ndarray, adjusted_close: np.ndarray) -> pd.DataFrame:
    """Never detect events or infer confirmation times from stored extremes.

    All event rows are supplied P events. Missing support prices are feature
    unknown; malformed identities, future extremes and nonupper bonus lines
    are source-contract errors. Negative B/B2 distances remain valid values.
    """
    if (
        not isinstance(calendar, pd.DatetimeIndex)
        or calendar.tz is not None
        or calendar.hasnans
        or not calendar.is_unique
        or not calendar.is_monotonic_increasing
    ):
        raise ValueError("calendar must be unique, sorted, nonmissing and timezone-naive")
    if not calendar.equals(cast(Any, calendar).normalize()):
        raise ValueError("calendar must contain midnight dates")
    low, close = np.asarray(adjusted_low, dtype=float), np.asarray(adjusted_close, dtype=float)
    if low.ndim != 1 or close.ndim != 1 or len(low) != len(calendar) or len(close) != len(calendar):
        raise ValueError("adjusted arrays must be one-dimensional and match calendar")
    if not events.columns.is_unique or not events.index.is_unique or not set(REQUIRED_COLUMNS).issubset(events):
        raise ValueError("events require unique indices/columns and all original pattern fields")
    date_indices = {cast(pd.Timestamp, day): index for index, day in enumerate(calendar)}
    records: list[dict[str, Any]] = []
    for event in events.to_dict(orient="records"):
        position = event["calendar_index"]
        if isinstance(position, (bool, np.bool_)) or not isinstance(position, Integral):
            raise ValueError("calendar_index must be an in-range integer")
        position = int(position)
        if not 0 <= position < len(calendar):
            raise ValueError("calendar_index must be an in-range integer")
        t0 = cast(pd.Timestamp, calendar[position])
        if "Date" in event and _date(event["Date"], "event Date") != t0:
            raise ValueError("event Date does not match calendar_index")
        restart = _date(event["restart_date"], "restart_date")
        if restart not in date_indices or restart > t0:
            raise ValueError("restart_date must be a common-calendar date no later than t0")
        restart_index = date_indices[restart]
        anchor = close[position]
        levels = _json_list(event["bonus_levels"], "bonus_levels")
        seq = _json_list(event["pivot_sequence"], "pivot_sequence")
        for point in seq:
            if not {"k", "rel", "p", "date"}.issubset(point) or point["k"] not in {"H", "L"} or not isinstance(point["rel"], str) or not _positive(point["p"]):
                raise ValueError("pivot_sequence points require valid k/rel/p/date")
            extreme = _date(point["date"], "pivot extreme date")
            if extreme not in date_indices or extreme > t0:
                raise ValueError("pivot extreme date must be a common-calendar date no later than t0")
        category = event["cat"]
        if category not in {"bottom", "hhhl", "range"}:
            raise ValueError("unexpected original pattern category")
        if not isinstance(event["big_hhhl"], (bool, np.bool_)):
            raise ValueError("big_hhhl must be a boolean")
        row: dict[str, Any] = {feature: np.nan for feature in VALUE_COLUMNS}
        row.update({f"{feature}_unknown_reason": None for feature in REASON_FEATURES})
        row.update({
            "A_applicable": bool(levels),
            "E": position - restart_index,
            "E3": sum(point["rel"] == "higher" and point["k"] in {"H", "L"} for point in seq),
            "E4_cat": category,
            "E4_big": bool(event["big_hhhl"]),
            "G": event["vx"],
        })
        upper_levels = []
        for line in levels:
            if not {"age", "level"}.issubset(line) or not _positive(line["level"]):
                raise ValueError("bonus_levels require age and a finite positive level")
            if _positive(anchor) and line["level"] <= anchor:
                raise ValueError("bonus level must be strictly above t0 anchor")
            upper_levels.append(float(line["level"]))
        if upper_levels:
            if _positive(anchor):
                row["A"] = min(upper_levels) / anchor - 1
            else:
                row["A_unknown_reason"] = "invalid_anchor"
        for feature, support in (("B", event["Z2"]), ("B2", event["hz_top"])):
            if not _positive(anchor):
                row[f"{feature}_unknown_reason"] = "invalid_anchor"
            elif not _positive(support):
                row[f"{feature}_unknown_reason"] = "invalid_support"
            else:
                row[feature] = anchor / support - 1
        hz, restart_low = event["hz_top"], low[restart_index]
        if not _positive(hz):
            row["E2_unknown_reason"] = "invalid_support"
        elif not _positive(restart_low):
            row["E2_unknown_reason"] = "missing_restart_low"
        else:
            row["E2"] = (hz - restart_low) / hz
        records.append(row)
    columns = [*VALUE_COLUMNS, "A_applicable", *(f"{feature}_unknown_reason" for feature in REASON_FEATURES)]
    result = pd.DataFrame(records, index=events.index, columns=pd.Index(columns))
    result["A_applicable"] = result["A_applicable"].astype(bool)
    result["E4_big"] = result["E4_big"].astype(bool)
    LOGGER.debug("Calculated supplied pattern features events=%d overhead=%d", len(result), int(result.A_applicable.sum()))
    return result

"""Versioned calendar path outcomes and fixed-event failure observations.

All inputs are already aligned to the common calendar. No market readers,
detectors or price restoration run here. Bulk outcomes use O(n) working space.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from numbers import Integral
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_observations import classify_window, flag_history, landmark_riskset

LOGGER = logging.getLogger(__name__)


def _vector(values: np.ndarray) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.ndim != 1:
        raise ValueError("prices must be one-dimensional")
    return result


def _positive_integer(value: int, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _valid(values: np.ndarray) -> np.ndarray:
    return np.isfinite(values) & (values > 0)


def _optional_offsets(offsets: np.ndarray, sentinel: int) -> pd.arrays.IntegerArray:
    return cast(pd.arrays.IntegerArray, pd.array([None if value == sentinel else int(value) for value in offsets], dtype="Int64"))


def _diagnostic(
    first_true: np.ndarray,
    first_missing: np.ndarray,
    cutoff: np.ndarray,
    observed: np.ndarray,
    anchor_valid: np.ndarray,
    sentinel: int,
) -> tuple[np.ndarray, pd.arrays.IntegerArray]:
    triggered = anchor_valid & (first_true <= cutoff) & (first_true < first_missing)
    unknown = ~anchor_valid | ((first_missing <= cutoff) & ~triggered) | ((observed < cutoff) & ~triggered)
    states = np.full(len(cutoff), "all_false", dtype=object)
    states[unknown] = "unknown"
    states[triggered] = "triggered"
    return states, _optional_offsets(np.where(triggered, first_true, sentinel), sentinel)


def outcomes_for_closes(close: np.ndarray, horizon: int) -> pd.DataFrame:
    """Evaluate each common-calendar anchor with first-decision missingness.

    A horizon shift updates whole NumPy slices, rather than scanning individual
    anchor paths in Python. ``label`` retains observed censored hits;
    ``main_eligible`` independently excludes all calendar-incomplete windows.
    Drawdown diagnostics compare closes to the fixed anchor, not rolling peaks.
    """
    horizon = _positive_integer(horizon, "horizon")
    values = _vector(close)
    n = len(values)
    sentinel = horizon + 1
    positions = np.arange(n)
    anchor_valid = _valid(values)
    observed = np.minimum(horizon, n - positions - 1)
    calendar_full = observed == horizon
    missing = np.full(n, sentinel, dtype=np.int64)
    missing[~anchor_valid] = 0
    hit = np.full(n, sentinel, dtype=np.int64)
    lows = {name: np.full(n, sentinel, dtype=np.int64) for name in ("drawdown10", "drawdown20")}
    denominator = np.where(anchor_valid, values, 1.0)
    for offset in range(1, min(horizon, max(n - 1, 0)) + 1):
        stop = n - offset
        future = values[offset:]
        valid = _valid(future)
        missing[:stop] = np.where((missing[:stop] == sentinel) & ~valid, offset, missing[:stop])
        ratio = future / denominator[:stop]
        hit[:stop] = np.where((hit[:stop] == sentinel) & valid & (ratio >= 2.0), offset, hit[:stop])
        for name, threshold in (("drawdown10", 0.9), ("drawdown20", 0.8)):
            first = lows[name]
            first[:stop] = np.where((first[:stop] == sentinel) & valid & (future <= threshold * denominator[:stop]), offset, first[:stop])
    known_hit = anchor_valid & (hit < missing) & (hit != sentinel)
    accepted_hit = np.where(known_hit, hit, sentinel)
    full_path = calendar_full & anchor_valid & (missing == sentinel)
    terminal = np.full(n, np.nan)
    complete_indexes = np.flatnonzero(calendar_full)
    terminal[complete_indexes] = values[complete_indexes + horizon]
    labels = np.full(n, "unknown", dtype=object)
    labels[full_path & ~known_hit & (terminal < values)] = "loss"
    labels[full_path & ~known_hit & (terminal >= values)] = "flat-win"
    labels[known_hit] = "hit"
    reasons = np.full(n, None, dtype=object)
    unresolved = labels == "unknown"
    reasons[unresolved & ~anchor_valid] = "invalid_anchor"
    reasons[unresolved & anchor_valid & (missing != sentinel)] = "missing_before_hit"
    reasons[unresolved & anchor_valid & (missing == sentinel)] = "window_end"
    endpoint_valid = calendar_full & _valid(terminal)
    result: dict[str, Any] = {
        "calendar_full": calendar_full,
        "full_path": full_path,
        "label": labels,
        "first_hit_offset": _optional_offsets(accepted_hit, sentinel),
        "first_missing_offset": _optional_offsets(missing, sentinel),
        "unknown_reason": reasons,
        "main_eligible": calendar_full & (labels != "unknown"),
        "hit_then_below_anchor": known_hit & endpoint_valid & (terminal < values),
        "hit_endpoint_unknown": known_hit & ~endpoint_valid,
    }
    full_cutoff = np.full(n, horizon)
    before_cutoff = np.where(known_hit, hit - 1, horizon)
    for name, first in lows.items():
        states, offsets = _diagnostic(first, missing, full_cutoff, observed, anchor_valid, sentinel)
        result[f"{name}_full_state"] = states
        result[f"{name}_full_first_trigger_offset"] = offsets
        before_name = "before_hit10" if name == "drawdown10" else "before_hit20"
        states, offsets = _diagnostic(first, missing, before_cutoff, observed, anchor_valid, sentinel)
        result[f"{before_name}_state"] = states
        result[f"{before_name}_first_trigger_offset"] = offsets
    LOGGER.debug("Variants outcomes horizon=%d anchors=%d main=%d", horizon, n, result["main_eligible"].sum())
    return pd.DataFrame(result, index=pd.RangeIndex(n))


def _support_flag(close: float, level: float, *, inclusive: bool = False) -> bool | None:
    if not np.isfinite(close) or close <= 0 or not np.isfinite(level) or level <= 0:
        return None
    return bool(close <= level if inclusive else close < level)


def event_flag_records(
    close: np.ndarray,
    ma20: np.ndarray,
    ma60: np.ndarray,
    t0: int,
    z2: float,
    hz_top: float,
    restart_low: float,
    low_pivots: Sequence[tuple[int, int, float]],
    horizons: Sequence[int] = (126, 252),
    landmarks: Sequence[int] = (5, 10, 20, 40),
) -> list[dict[str, Any]]:
    """Observe eight flags at landmarks and at each complete horizon.

    Supplied pivot triples must cover the frozen source's complete observed
    path. X4 uses confirmation indexes, including extrema before t0, and does
    not invent unknown pivot days from missing common-calendar daily closes.
    ``flag_*`` fields strictly precede first hit; ``raw_flag_*`` ignore hits.
    """
    closes, short_ma, long_ma = (_vector(item) for item in (close, ma20, ma60))
    if not len(closes) == len(short_ma) == len(long_ma):
        raise ValueError("close and moving averages must have equal length")
    t0 = _positive_integer(t0, "t0", minimum=0)
    if t0 >= len(closes):
        raise ValueError("t0 must be in range")
    horizon_values = tuple(_positive_integer(value, "horizon") for value in horizons)
    landmark_values = tuple(_positive_integer(value, "landmark") for value in landmarks)
    if len(set(horizon_values)) != len(horizon_values) or len(set(landmark_values)) != len(landmark_values):
        raise ValueError("horizons and landmarks must be unique")
    crossing_indexes: set[int] = set()
    for extreme, confirmed, price in low_pivots:
        extreme = _positive_integer(extreme, "extreme", minimum=0)
        confirmed = _positive_integer(confirmed, "confirmed", minimum=0)
        if not extreme <= confirmed < len(closes) or not np.isfinite(price) or price <= 0:
            raise ValueError("invalid supplied low pivot")
        if confirmed > t0 and price < z2:
            crossing_indexes.add(confirmed)
    max_horizon = max(horizon_values, default=0)
    stop = min(len(closes), t0 + max_horizon + 1)
    path = closes[t0:stop].tolist()
    anchor = closes[t0]
    flag_vectors: dict[str, list[bool | None]] = {name: [] for name in ("X1", "X2", "X3", "X4", "X5_MA20", "X5_MA60", "X6_10", "X6_15")}
    pivot_known = bool(np.isfinite(z2) and z2 > 0)
    for index in range(t0, stop):
        observed_close = closes[index]
        levels = {"X1": hz_top, "X2": z2, "X3": restart_low, "X5_MA20": short_ma[index], "X5_MA60": long_ma[index]}
        for name, level in levels.items():
            flag_vectors[name].append(_support_flag(observed_close, level))
        flag_vectors["X4"].append(index in crossing_indexes if pivot_known else None)
        flag_vectors["X6_10"].append(_support_flag(observed_close, anchor * 0.9, inclusive=True))
        flag_vectors["X6_15"].append(_support_flag(observed_close, anchor * 0.85, inclusive=True))
    records: list[dict[str, Any]] = []
    # NEW riskset does not depend on Z2; a benign valid stand-in lets the shared
    # helper retain its validation while missing Z2 is isolated to LEGACY/X2/X4.
    valid_z2 = bool(np.isfinite(z2) and z2 > 0)
    for horizon in horizon_values:
        outcome = classify_window(path, horizon)
        for landmark in (*[value for value in landmark_values if value < horizon], horizon):
            riskset = landmark_riskset(path, landmark, z2 if valid_z2 else 1.0)
            legacy = landmark_riskset(path, landmark, z2, legacy_active=True) if valid_z2 else None
            ratio = (
                float(path[landmark] / anchor)
                if landmark < len(path) and np.isfinite(anchor) and anchor > 0 and np.isfinite(path[landmark]) and path[landmark] > 0
                else None
            )
            rise_bin = None if ratio is None else "lt1" if ratio < 1 else "b1_1p10" if ratio < 1.1 else "b1p10_1p25" if ratio < 1.25 else "ge1p25"
            for name, flags in flag_vectors.items():
                raw = flag_history(flags, landmark)
                before = flag_history(flags, landmark, outcome.first_hit_offset)
                offset = before.first_trigger_offset
                trigger_return = (
                    float(path[offset] / anchor - 1.0)
                    if offset is not None and np.isfinite(anchor) and anchor > 0 and np.isfinite(path[offset]) and path[offset] > 0
                    else None
                )
                records.append({
                    "horizon": horizon,
                    "landmark": landmark,
                    "scope": "full" if landmark == horizon else "landmark",
                    "flag_id": name,
                    "flag_state": before.state,
                    "first_trigger_offset": offset,
                    "unknown_reason": before.reason,
                    "through_offset": before.through_offset,
                    "trigger_return": trigger_return,
                    "raw_flag_state": raw.state,
                    "raw_first_trigger_offset": raw.first_trigger_offset,
                    "raw_unknown_reason": raw.reason,
                    "riskset_id": riskset.riskset_id,
                    "riskset_state": riskset.state,
                    "riskset_reason": riskset.reason,
                    "riskset_decision_offset": riskset.decision_offset,
                    "riskset_eligible": riskset.eligible,
                    "legacy_state": legacy.state if legacy else "early_unknown",
                    "legacy_reason": legacy.reason if legacy else "invalid_support",
                    "legacy_decision_offset": legacy.decision_offset if legacy else None,
                    "rise_ratio": ratio,
                    "rise_bin": rise_bin,
                    "calendar_full": outcome.calendar_full,
                    "full_path": outcome.full_path,
                    "label": outcome.outcome,
                    "first_hit_offset": outcome.first_hit_offset,
                    "outcome_unknown_reason": outcome.reason,
                })
    LOGGER.debug("Variants flags t0=%d records=%d", t0, len(records))
    return records

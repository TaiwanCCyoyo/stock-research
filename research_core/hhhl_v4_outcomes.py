"""First-decision HHHL v4 outcomes and fixed-landmark measurements.

Inputs are one security's closes on the shared calendar. Missing or invalid
closes remain missing calendar observations; they are never skipped or filled.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_probability import OUTCOME_COLUMNS

LOGGER = logging.getLogger(__name__)
HORIZONS = (63, 126)
TARGETS = {63: 1.5, 126: 2.0}
_VALID_BONUS_AGES = frozenset(("old", "recent_far"))


def _close_vector(close: np.ndarray) -> np.ndarray:
    """Convert a one-dimensional close sequence without treating bad values as zero."""
    try:
        raw = np.asarray(close)
    except (TypeError, ValueError) as exc:
        raise ValueError("close must be a one-dimensional float-coercible array") from exc
    if raw.ndim != 1:
        raise ValueError("close must be one-dimensional")
    try:
        numeric = cast(pd.Series, pd.to_numeric(pd.Series(raw), errors="raise"))
        return numeric.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("close values must be float-coercible") from exc


def _valid_prices(values: np.ndarray) -> np.ndarray:
    return np.isfinite(values) & (values > 0)


def _horizon_outcomes(values: np.ndarray, horizon: int, target: float) -> dict[str, np.ndarray]:
    """Evaluate every anchor with vectorized calendar windows."""
    n = len(values)
    anchors = np.arange(n, dtype=np.int64)
    offsets = np.arange(1, horizon + 1, dtype=np.int64)
    positions = anchors[:, None] + offsets[None, :]
    in_bounds = positions < n

    # Empty input yields an empty (0, horizon) matrix and remains well-defined.
    safe_positions = np.minimum(positions, max(n - 1, 0))
    future = values[safe_positions]
    future_valid = in_bounds & _valid_prices(future)
    anchor_valid = _valid_prices(values)
    observed = future_valid.sum(axis=1, dtype=np.int64)

    has_missing = (~future_valid & in_bounds).any(axis=1)
    first_missing = np.where(
        has_missing,
        np.argmax(~future_valid & in_bounds, axis=1) + 1,
        horizon + 1,
    )
    denominator = np.where(anchor_valid, values, 1.0)
    hit_matrix = future_valid & (future / denominator[:, None] >= target)
    has_hit = hit_matrix.any(axis=1)
    first_hit = np.where(has_hit, np.argmax(hit_matrix, axis=1) + 1, horizon + 1)
    hit_before_missing = anchor_valid & has_hit & (first_hit < first_missing)

    full_horizon = in_bounds.all(axis=1)
    complete = anchor_valid & full_horizon & future_valid.all(axis=1)
    no_hit_complete = complete & ~has_hit

    labels = np.full(n, np.nan, dtype=float)
    labels[hit_before_missing] = 1.0
    labels[no_hit_complete] = 0.0

    waits = np.full(n, np.nan, dtype=float)
    waits[hit_before_missing] = first_hit[hit_before_missing]

    reasons = np.full(n, None, dtype=object)
    reasons[~anchor_valid] = "invalid_anchor"
    unresolved = anchor_valid & ~hit_before_missing
    reasons[unresolved & has_missing] = "missing_before_hit"
    reasons[unresolved & ~has_missing & ~full_horizon] = "window_end"

    maximum = np.full(n, np.nan, dtype=float)
    minimum = np.full(n, np.nan, dtype=float)
    drawdown = np.full(n, np.nan, dtype=float)
    forward = np.full(n, np.nan, dtype=float)
    full_rows = np.flatnonzero(complete)
    if len(full_rows):
        full_future = future[full_rows]
        full_anchor = values[full_rows]
        relative = full_future / full_anchor[:, None]
        maximum[full_rows] = relative.max(axis=1) - 1.0
        minimum[full_rows] = relative.min(axis=1) - 1.0
        forward[full_rows] = relative[:, -1] - 1.0
        path = np.column_stack((full_anchor, full_future))
        peaks = np.maximum.accumulate(path, axis=1)
        drawdown[full_rows] = np.max(1.0 - path / peaks, axis=1)

    return {
        f"label_{horizon}": labels,
        f"complete_{horizon}": complete,
        f"unknown_reason_{horizon}": reasons,
        f"max_return_{horizon}": maximum,
        f"min_return_{horizon}": minimum,
        f"max_drawdown_{horizon}": drawdown,
        f"forward_return_{horizon}": forward,
        f"wait_to_threshold_{horizon}": waits,
        f"observed_sessions_{horizon}": observed,
    }


def first_decision_outcomes(close: np.ndarray) -> pd.DataFrame:
    """Return 63-session 1.5x and 126-session 2x first-decision outcomes.

    A hit is known as soon as it precedes the first invalid future close. If an
    invalid close comes first, later closes cannot repair that unknown result.
    Path metrics are available only for a fully observed anchor-to-deadline
    path, even when an earlier hit already made the label known.
    """
    values = _close_vector(close)
    results: dict[str, np.ndarray] = {}
    for horizon in HORIZONS:
        results.update(_horizon_outcomes(values, horizon, TARGETS[horizon]))
    columns = [*OUTCOME_COLUMNS, *(f"observed_sessions_{h}" for h in HORIZONS)]
    LOGGER.debug("Computed HHHL v4 first-decision outcomes anchors=%d", len(values))
    return pd.DataFrame(results, index=pd.RangeIndex(len(values))).loc[:, columns]


def _bonus_levels(levels: list[dict[str, Any]]) -> list[tuple[str, float]]:
    if not isinstance(levels, list):
        raise ValueError("bonus_levels must be a list")
    parsed: list[tuple[str, float]] = []
    for index, item in enumerate(levels):
        if not isinstance(item, Mapping):
            raise ValueError(f"bonus_levels[{index}] must be a mapping")
        age = item.get("age")
        if not isinstance(age, str) or age not in _VALID_BONUS_AGES:
            raise ValueError(f"bonus_levels[{index}].age must be old or recent_far")
        try:
            level = float(item["level"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"bonus_levels[{index}].level must be a finite positive number") from exc
        if not math.isfinite(level) or level <= 0:
            raise ValueError(f"bonus_levels[{index}].level must be a finite positive number")
        parsed.append((str(age), level))
    return parsed


def _first_true(values: np.ndarray) -> int | None:
    found = np.flatnonzero(values)
    return int(found[0]) if len(found) else None


def _active_bonus_summary(
    values: np.ndarray,
    anchor: int,
    landmark: int,
    levels: list[tuple[str, float]],
) -> dict[str, Any]:
    path = values[anchor + 1 : anchor + landmark + 1]
    positions = np.arange(anchor + 1, anchor + landmark + 1, dtype=np.int64)
    first_cross: dict[str, int | None] = {"old": None, "recent_far": None}
    for age, level in levels:
        crossed = path > level
        offset = _first_true(crossed)
        if offset is not None:
            calendar_position = int(positions[offset])
            previous = first_cross[age]
            if previous is None or calendar_position < previous:
                first_cross[age] = calendar_position

    cross_old = first_cross["old"] is not None
    cross_recent_far = first_cross["recent_far"] is not None
    if not levels:
        group = "clean_reference"
    elif cross_old and cross_recent_far:
        group = "cross_both"
    elif cross_old:
        group = "cross_old_only"
    elif cross_recent_far:
        group = "cross_recent_far_only"
    else:
        group = "uncrossed_overhead"
    return {
        "cross_old": cross_old,
        "cross_recent_far": cross_recent_far,
        "first_cross_old_index": first_cross["old"],
        "first_cross_recent_far_index": first_cross["recent_far"],
        "bonus_group": group,
    }


def _remaining_outcome(values: np.ndarray, anchor: int, landmark: int) -> dict[str, Any]:
    """Evaluate offsets landmark+1 through the original offset 126 deadline."""
    horizon = 126
    start = anchor + landmark + 1
    deadline = anchor + horizon
    observed_stop = min(deadline + 1, len(values))
    future_positions = np.arange(start, observed_stop, dtype=np.int64)
    future = values[start:observed_stop]
    valid = _valid_prices(future)
    ratio = future / values[anchor]
    hits = valid & (ratio >= TARGETS[horizon])
    first_hit_offset = _first_true(hits)
    missing_offset = _first_true(~valid)
    full_remaining = observed_stop == deadline + 1
    complete = full_remaining and bool(valid.all())

    label: int | None = None
    reason: str | None = None
    wait_to_threshold: int | None = None
    wait_from_landmark: int | None = None
    hit_precedes_missing = first_hit_offset is not None and (missing_offset is None or first_hit_offset < missing_offset)
    if hit_precedes_missing:
        label = 1
        hit_position = int(future_positions[first_hit_offset])
        wait_to_threshold = hit_position - anchor
        wait_from_landmark = hit_position - (anchor + landmark)
    elif missing_offset is not None:
        reason = "missing_before_hit"
    elif not full_remaining:
        reason = "window_end"
    else:
        label = 0

    metrics: dict[str, float | None] = {
        "max_return_126": None,
        "min_return_126": None,
        "max_drawdown_126": None,
        "forward_return_126": None,
    }
    if complete:
        remaining_relative = future / values[anchor]
        drawdown_path = values[anchor + landmark : deadline + 1]
        metrics = {
            "max_return_126": float(remaining_relative.max() - 1.0),
            "min_return_126": float(remaining_relative.min() - 1.0),
            "max_drawdown_126": float(np.max(1.0 - drawdown_path / np.maximum.accumulate(drawdown_path))),
            "forward_return_126": float(values[deadline] / values[anchor] - 1.0),
        }
    return {
        "label_126": label,
        "unknown_reason_126": reason,
        "wait_to_threshold_126": wait_to_threshold,
        "wait_from_landmark": wait_from_landmark,
        "complete_126": bool(complete),
        **metrics,
    }


def landmark_record(
    close: np.ndarray,
    anchor: int,
    landmark: int,
    z2: float,
    bonus_levels: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify the original t0+L status and measure only its active remainder.

    Landmark offsets use the supplied shared-calendar array. The 2x target and
    final deadline remain anchored to the original close; neither restarts at L.
    """
    values = _close_vector(close)
    if isinstance(anchor, (bool, np.bool_)) or not isinstance(anchor, (int, np.integer)):
        raise ValueError("anchor must be an in-range integer")
    anchor = int(anchor)
    if anchor < 0 or anchor >= len(values):
        raise ValueError("anchor must be an in-range integer")
    if isinstance(landmark, (bool, np.bool_)) or not isinstance(landmark, (int, np.integer)):
        raise ValueError("landmark must be a positive integer")
    landmark = int(landmark)
    if landmark <= 0 or landmark >= 126:
        raise ValueError("landmark must be a positive integer below the 126-session deadline")
    try:
        fixed_z2 = float(z2)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("z2 must be a finite positive number") from exc
    if not math.isfinite(fixed_z2) or fixed_z2 <= 0:
        raise ValueError("z2 must be a finite positive number")
    parsed_levels = _bonus_levels(bonus_levels)

    anchor_close = values[anchor]
    landmark_index = anchor + landmark
    result: dict[str, Any] = {
        "landmark": landmark,
        "landmark_index": landmark_index if landmark_index < len(values) else None,
        "status": "unknown",
        "reason": None,
        "rise_ratio": None,
        "rise_bin": None,
        "cross_old": None,
        "cross_recent_far": None,
        "first_cross_old_index": None,
        "first_cross_recent_far_index": None,
        "group": None,
        "label_126": None,
        "unknown_reason_126": None,
        "wait_to_threshold_126": None,
        "wait_from_landmark": None,
        "complete_126": None,
        "max_return_126": None,
        "min_return_126": None,
        "max_drawdown_126": None,
        "forward_return_126": None,
    }

    if not _valid_prices(np.asarray([anchor_close]))[0]:
        result["reason"] = "invalid_anchor"
        LOGGER.debug("HHHL v4 landmark status=unknown reason=invalid_anchor anchor=%d L=%d", anchor, landmark)
        return result

    observed_stop = min(landmark_index + 1, len(values))
    path = values[anchor + 1 : observed_stop]
    valid = _valid_prices(path)
    missing_position = _first_true(~valid)
    hit_position = _first_true(valid & (path / anchor_close >= 2.0))
    failed_position = _first_true(valid & (path < fixed_z2))
    event_positions = [position for position in (hit_position, failed_position) if position is not None]
    first_status_event = min(event_positions) if event_positions else None

    if missing_position is not None and (first_status_event is None or missing_position < first_status_event):
        result["reason"] = "missing_before_landmark"
    elif hit_position is not None and (failed_position is None or hit_position <= failed_position):
        result["status"] = "early_hit"
    elif failed_position is not None:
        result["status"] = "early_failed"
    elif observed_stop <= landmark_index:
        result["reason"] = "window_end"
    else:
        result["status"] = "active"

    if result["status"] == "active":
        endpoint = float(values[landmark_index])
        ratio = endpoint / float(anchor_close)
        result["rise_ratio"] = ratio
        if ratio < 1.0:
            result["rise_bin"] = "lt1"
        elif ratio < 1.1:
            result["rise_bin"] = "b1_1p10"
        elif ratio < 1.25:
            result["rise_bin"] = "b1p10_1p25"
        else:
            result["rise_bin"] = "ge1p25"
        bonus_summary = _active_bonus_summary(values, anchor, landmark, parsed_levels)
        result.update({key: value for key, value in bonus_summary.items() if key != "bonus_group"})
        result["group"] = bonus_summary["bonus_group"]
        result.update(_remaining_outcome(values, anchor, landmark))

    LOGGER.debug(
        "HHHL v4 landmark anchor=%d L=%d status=%s reason=%s",
        anchor,
        landmark,
        result["status"],
        result["reason"],
    )
    return result

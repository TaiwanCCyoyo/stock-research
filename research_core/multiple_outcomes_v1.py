"""Versioned multiple-target calendar outcomes (``multiple-outcomes.v1``).

``hhhl_variants_paths.outcomes_for_closes`` fixes the target at 2x and also
returns drawdown diagnostics. This module keeps its first-decision rules and
generalizes only the target multiple, so several targets share one horizon
scan. At target 2.0 every returned column equals the same-named column of
``outcomes_for_closes``; drawdown diagnostics are not produced here.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from numbers import Real
from typing import Any

import numpy as np
import pandas as pd

from research_core.hhhl_variants_paths import _optional_offsets, _positive_integer, _valid, _vector

LOGGER = logging.getLogger(__name__)

DEFINITION_ID = "multiple-outcomes.v1"
COLUMNS = (
    "calendar_full",
    "full_path",
    "label",
    "first_hit_offset",
    "first_missing_offset",
    "unknown_reason",
    "main_eligible",
    "hit_then_below_anchor",
    "hit_endpoint_unknown",
)


def _targets(values: Sequence[float]) -> tuple[float, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise ValueError("targets must be a nonempty sequence")
    result: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(float(value)) or float(value) <= 1.0:
            raise ValueError("each target must be a finite multiple greater than 1")
        result.append(float(value))
    if len(set(result)) != len(result):
        raise ValueError("targets must be unique")
    return tuple(result)


def outcomes_for_targets(close: np.ndarray, horizon: int, targets: Sequence[float]) -> dict[float, pd.DataFrame]:
    """Evaluate every common-calendar anchor once per target multiple.

    For each anchor t0, the first close in t0+1..t0+horizon at or above
    ``target`` x anchor is a hit unless an invalid close occurs first, which
    makes the outcome unknown. A complete valid path without a hit is a loss
    when the terminal close is below the anchor and a flat-win otherwise.
    Observed censored hits keep ``label='hit'`` with ``main_eligible=False``.
    Inputs are already aligned to the common calendar; nothing is read,
    filled, dropped or restored here.
    """
    horizon = _positive_integer(horizon, "horizon")
    multiples = _targets(targets)
    values = _vector(close)
    n = len(values)
    sentinel = horizon + 1
    positions = np.arange(n)
    anchor_valid = _valid(values)
    observed = np.minimum(horizon, n - positions - 1)
    calendar_full = observed == horizon
    missing = np.full(n, sentinel, dtype=np.int64)
    missing[~anchor_valid] = 0
    hits = {target: np.full(n, sentinel, dtype=np.int64) for target in multiples}
    denominator = np.where(anchor_valid, values, 1.0)
    for offset in range(1, min(horizon, max(n - 1, 0)) + 1):
        stop = n - offset
        future = values[offset:]
        valid = _valid(future)
        missing[:stop] = np.where((missing[:stop] == sentinel) & ~valid, offset, missing[:stop])
        ratio = future / denominator[:stop]
        for target, hit in hits.items():
            hit[:stop] = np.where((hit[:stop] == sentinel) & valid & (ratio >= target), offset, hit[:stop])
    full_path = calendar_full & anchor_valid & (missing == sentinel)
    terminal = np.full(n, np.nan)
    complete_indexes = np.flatnonzero(calendar_full)
    terminal[complete_indexes] = values[complete_indexes + horizon]
    endpoint_valid = calendar_full & _valid(terminal)
    result: dict[float, pd.DataFrame] = {}
    for target, hit in hits.items():
        known_hit = anchor_valid & (hit < missing) & (hit != sentinel)
        labels = np.full(n, "unknown", dtype=object)
        labels[full_path & ~known_hit & (terminal < values)] = "loss"
        labels[full_path & ~known_hit & (terminal >= values)] = "flat-win"
        labels[known_hit] = "hit"
        reasons = np.full(n, None, dtype=object)
        unresolved = labels == "unknown"
        reasons[unresolved & ~anchor_valid] = "invalid_anchor"
        reasons[unresolved & anchor_valid & (missing != sentinel)] = "missing_before_hit"
        reasons[unresolved & anchor_valid & (missing == sentinel)] = "window_end"
        frame: dict[str, Any] = {
            "calendar_full": calendar_full,
            "full_path": full_path,
            "label": labels,
            "first_hit_offset": _optional_offsets(np.where(known_hit, hit, sentinel), sentinel),
            "first_missing_offset": _optional_offsets(missing, sentinel),
            "unknown_reason": reasons,
            "main_eligible": calendar_full & (labels != "unknown"),
            "hit_then_below_anchor": known_hit & endpoint_valid & (terminal < values),
            "hit_endpoint_unknown": known_hit & ~endpoint_valid,
        }
        result[target] = pd.DataFrame(frame, index=pd.RangeIndex(n))
        LOGGER.debug("Multiple outcomes horizon=%d target=%s anchors=%d main=%d", horizon, target, n, frame["main_eligible"].sum())
    return result

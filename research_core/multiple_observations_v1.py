"""Multiple-target versions of PR17's public calendar observation clocks.

Only the target is generalized. Returned immutable records are the original
types so target 2.0 compares field-for-field with the frozen twofold helpers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from numbers import Integral, Real
from typing import Literal

from research_core.hhhl_variants_observations import LandmarkRiskset, Price, WindowObservation

DEFINITION_ID = "multiple-observations.v1"


def positive_offset(value: int, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def target_value(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value) or value <= 1:
        raise ValueError("target_multiple must be finite and greater than 1")
    return float(value)


def valid_price(value: Price) -> bool:
    return value is not None and math.isfinite(value) and value > 0


def classify_window(closes: Sequence[Price], horizon: int, target_multiple: float = 2.0) -> WindowObservation:
    """A first known hit absorbs later missingness; censoring is unchanged."""
    horizon, target = positive_offset(horizon, "horizon"), target_value(target_multiple)
    path = closes[: horizon + 1]
    calendar_full = len(closes) >= horizon + 1
    full_path = calendar_full and all(valid_price(value) for value in path)
    first_missing = next((i for i, value in enumerate(path) if not valid_price(value)), None)
    hit: int | None = None
    outcome: Literal["hit", "loss", "flat-win", "unknown"] = "unknown"
    reason: str | None = "invalid_anchor"
    if path and valid_price(path[0]):
        anchor = path[0]
        assert anchor is not None
        reason = "window_end"
        for offset, close in enumerate(path[1:], start=1):
            if not valid_price(close):
                reason = "missing_before_hit"
                break
            assert close is not None
            if close / anchor >= target:
                hit, outcome, reason = offset, "hit", None
                break
        else:
            if calendar_full:
                endpoint = path[-1]
                assert endpoint is not None
                outcome, reason = ("loss" if endpoint < anchor else "flat-win"), None
    return WindowObservation(outcome, calendar_full, full_path, hit, first_missing, reason, calendar_full and outcome != "unknown")


def landmark_riskset(closes: Sequence[Price], landmark: int, z2: float = 1.0, *, target_multiple: float = 2.0, legacy_active: bool = False) -> LandmarkRiskset:
    """Entire t0..L must be valid, including observations after an early hit."""
    landmark, target = positive_offset(landmark, "landmark"), target_value(target_multiple)
    if not valid_price(z2):
        raise ValueError("z2 must be finite and positive")
    identity: Literal["new_no_hit_valid_prefix", "legacy_active"] = "legacy_active" if legacy_active else "new_no_hit_valid_prefix"
    if len(closes) == 0 or not valid_price(closes[0]):
        return LandmarkRiskset(identity, "early_unknown", "invalid_anchor", 0)
    anchor = closes[0]
    assert anchor is not None
    first_hit: int | None = None
    for offset, close in enumerate(closes[1 : landmark + 1], start=1):
        if not valid_price(close):
            return LandmarkRiskset(identity, "early_unknown", "missing_before_landmark", offset)
        assert close is not None
        if close / anchor >= target:
            if legacy_active:
                return LandmarkRiskset(identity, "early_hit", None, offset)
            if first_hit is None:
                first_hit = offset
        if legacy_active and close < z2:
            return LandmarkRiskset(identity, "early_failed", None, offset)
    if len(closes) < landmark + 1:
        return LandmarkRiskset(identity, "early_unknown", "window_end", None)
    if first_hit is not None:
        return LandmarkRiskset(identity, "early_hit", None, first_hit)
    return LandmarkRiskset(identity, "active", None, None)

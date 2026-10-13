"""Pure session-index primitives for the prospective pattern-scan mission.

Inputs are one stock's prices aligned to the common trading calendar, including
missing sessions. Callers group cooldown events by stock and pattern, merging
subtypes first for a union row. These helpers never detect patterns or label hits.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from numbers import Real
from typing import Literal

log = logging.getLogger(__name__)
PathCategory = Literal["direct_failure", "rise_then_fall", "sideways", "slow_decline", "unknown"]


@dataclass(frozen=True)
class Episode:
    start_indices: tuple[int, ...]
    anchor_index: int | None
    peak_index: int | None
    status: Literal["known", "unknown"]
    reason: str | None = None


@dataclass(frozen=True)
class PathDescription:
    category: PathCategory
    reason: str | None = None
    max_return: float | None = None
    min_return: float | None = None
    peak_offset: int | None = None
    first_minus_10_offset: int | None = None
    first_plus_10_offset: int | None = None


def _index(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("session indices must be nonnegative integers")
    return value


def _indices(values: Iterable[int]) -> tuple[int, ...]:
    return tuple(sorted({_index(value) for value in values}))


def _close(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("closes must be real numbers or None")
    return float(value) if math.isfinite(value) and value > 0 else None


def per_group_cooldown(session_indices: Iterable[int]) -> tuple[int, ...]:
    """Deduplicate one stock+pattern group; suppress the next 20 sessions.

    Duplicate subtype indices are unioned before suppression. Suppressed candidates
    do not restart the cooldown. Apply independently to controls and each pattern;
    never mix stocks or patterns in a call. An index difference of 21 is eligible.
    """
    retained: list[int] = []
    candidates = _indices(session_indices)
    for index in candidates:
        if not retained or index - retained[-1] > 20:
            retained.append(index)
    log.debug("Cooldown retained %d of %d group indices", len(retained), len(candidates))
    return tuple(retained)


def _window(closes: Sequence[float | None], anchor: int, horizon: int) -> tuple[tuple[float, ...], str | None]:
    _index(anchor)
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("horizon must be a positive integer")
    if anchor >= len(closes):
        raise ValueError("anchor is outside the supplied calendar")
    if anchor + horizon >= len(closes):
        return (), "incomplete_window"
    values = tuple(_close(value) for value in closes[anchor : anchor + horizon + 1])
    if any(value is None for value in values):
        return (), "missing_or_invalid_price"
    return tuple(value for value in values if value is not None), None


def merge_hit_episodes(known_complete_hit_indices: Iterable[int], closes: Sequence[float | None]) -> tuple[Episode, ...]:
    """Merge caller-supplied, known, calendar-complete H126 hit starts.

    The caller obtains eligibility and hits from the existing label implementation;
    unknown, nonhit and incomplete-calendar starts must not be supplied. All indices
    refer to ONE stock's common calendar. Consecutive gaps <=20 merge transitively.
    The anchor is the minimum close among supplied starts (earliest on ties), not
    among intervening days. The peak is in anchor+1..anchor+126, earliest on ties.
    Missing anchor candidates or any invalid/incomplete peak window yield unknown;
    no gap is removed and no partial-window peak is reported.
    """
    indices = _indices(known_complete_hit_indices)
    if indices and indices[-1] >= len(closes):
        raise ValueError("hit start is outside the supplied calendar")
    groups: list[list[int]] = []
    for index in indices:
        if not groups or index - groups[-1][-1] > 20:
            groups.append([])
        groups[-1].append(index)
    result: list[Episode] = []
    for group in groups:
        candidates = [_close(closes[index]) for index in group]
        if any(value is None for value in candidates):
            result.append(Episode(tuple(group), None, None, "unknown", "missing_or_invalid_anchor"))
            continue
        known_anchors = [(index, value) for index, value in zip(group, candidates, strict=True) if value is not None]
        anchor = min(known_anchors, key=lambda item: (item[1], item[0]))[0]
        window, reason = _window(closes, anchor, 126)
        if reason:
            result.append(Episode(tuple(group), anchor, None, "unknown", reason))
            continue
        peak_offset = max(range(1, 127), key=lambda offset: (window[offset], -offset))
        result.append(Episode(tuple(group), anchor, anchor + peak_offset, "known"))
    log.debug("Merged %d hit starts into %d episodes", len(indices), len(result))
    return tuple(result)


def describe_price_path(closes: Sequence[float | None], anchor_index: int, *, horizon: int) -> PathDescription:
    """Describe all subsequent closes 1..horizon relative to the anchor.

    Ordered rules apply identically to caller-labelled hit and nonhit events. The
    rise_then_fall name is a descriptive bin (max >=20%), not a verified drawdown.
    If -10% occurs and +10% never occurs, direct_failure takes precedence. Prices
    on exact thresholds count; sideways requires strictly greater than -15%.
    Unknown is explicit even when a partial window already crossed a threshold.
    """
    window, reason = _window(closes, anchor_index, horizon)
    if reason:
        return PathDescription("unknown", reason)
    base, future = window[0], window[1:]
    minus = next((i for i, close in enumerate(future, 1) if close / base <= 0.9), None)
    plus = next((i for i, close in enumerate(future, 1) if close / base >= 1.1), None)
    peak_offset = max(range(1, horizon + 1), key=lambda i: (window[i], -i))
    maximum, minimum = max(future), min(future)
    category: PathCategory
    if minus is not None and (plus is None or minus < plus):
        category = "direct_failure"
    elif maximum / base >= 1.2:
        category = "rise_then_fall"
    elif maximum / base < 1.2 and minimum / base > 0.85:
        category = "sideways"
    else:
        category = "slow_decline"
    return PathDescription(category, None, maximum / base - 1, minimum / base - 1, peak_offset, minus, plus)

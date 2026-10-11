"""Pure calendar observations for preregistered HHHL variants.

Offsets count supplied common-calendar rows, including invalid observations.
These helpers neither load market data nor interpret outcomes as account returns.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from numbers import Integral
from typing import Literal

Price = float | None


def _offset(value: int, name: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


def _valid(value: Price) -> bool:
    return value is not None and math.isfinite(value) and value > 0


@dataclass(frozen=True)
class WindowObservation:
    outcome: Literal["hit", "loss", "flat-win", "unknown"]
    calendar_full: bool
    full_path: bool
    first_hit_offset: int | None
    first_missing_offset: int | None
    reason: str | None
    main_eligible: bool


def classify_window(closes: Sequence[Price], horizon: int) -> WindowObservation:
    """Classify a fixed 2x window; a first hit absorbs later missingness."""
    horizon = _offset(horizon, "horizon")
    path = closes[: horizon + 1]
    calendar_full = len(closes) >= horizon + 1
    full_path = calendar_full and all(_valid(value) for value in path)
    first_missing = next((i for i, value in enumerate(path) if not _valid(value)), None)
    hit: int | None = None
    outcome: Literal["hit", "loss", "flat-win", "unknown"] = "unknown"
    reason: str | None = "invalid_anchor"
    if path and _valid(path[0]):
        anchor = path[0]
        assert anchor is not None
        reason = "window_end"
        for offset, close in enumerate(path[1:], start=1):
            if not _valid(close):
                reason = "missing_before_hit"
                break
            assert close is not None
            if close / anchor >= 2.0:
                hit, outcome, reason = offset, "hit", None
                break
        else:
            if calendar_full:
                endpoint = path[-1]
                assert endpoint is not None
                outcome, reason = ("loss" if endpoint < anchor else "flat-win"), None
    return WindowObservation(outcome, calendar_full, full_path, hit, first_missing, reason, calendar_full and outcome != "unknown")


@dataclass(frozen=True)
class LandmarkRiskset:
    riskset_id: Literal["new_no_hit_valid_prefix", "legacy_active"]
    state: Literal["active", "early_hit", "early_failed", "early_unknown"]
    reason: str | None
    decision_offset: int | None

    @property
    def eligible(self) -> bool:
        return self.state == "active"


def landmark_riskset(closes: Sequence[Price], landmark: int, z2: float, *, legacy_active: bool = False) -> LandmarkRiskset:
    """NEW ignores support breaks; LEGACY absorbs its first chronological event.

    NEW requires the entire t0..L prefix valid, even after an earlier hit.
    LEGACY begins support-break comparisons at t0+1, against the fixed t0 Z2.
    """
    landmark = _offset(landmark, "landmark")
    if not _valid(z2):
        raise ValueError("z2 must be finite and positive")
    riskset_id: Literal["new_no_hit_valid_prefix", "legacy_active"] = "legacy_active" if legacy_active else "new_no_hit_valid_prefix"
    if len(closes) == 0 or not _valid(closes[0]):
        return LandmarkRiskset(riskset_id, "early_unknown", "invalid_anchor", 0)
    anchor = closes[0]
    assert anchor is not None
    first_hit: int | None = None
    for offset, close in enumerate(closes[1 : landmark + 1], start=1):
        if not _valid(close):
            return LandmarkRiskset(riskset_id, "early_unknown", "missing_before_landmark", offset)
        assert close is not None
        if close / anchor >= 2.0:
            if legacy_active:
                return LandmarkRiskset(riskset_id, "early_hit", None, offset)
            if first_hit is None:
                first_hit = offset
        if legacy_active and close < z2:
            return LandmarkRiskset(riskset_id, "early_failed", None, offset)
    if len(closes) < landmark + 1:
        return LandmarkRiskset(riskset_id, "early_unknown", "window_end", None)
    if first_hit is not None:
        return LandmarkRiskset(riskset_id, "early_hit", None, first_hit)
    return LandmarkRiskset(riskset_id, "active", None, None)


@dataclass(frozen=True)
class FlagHistory:
    state: Literal["triggered", "all_false", "unknown"]
    first_trigger_offset: int | None
    reason: str | None
    through_offset: int


def flag_history(flags: Sequence[bool | None], through_offset: int, first_hit_offset: int | None = None) -> FlagHistory:
    """Observe 1..L inclusive, strictly before a supplied first hit; ignore t0."""
    cutoff = _offset(through_offset, "through_offset", minimum=0)
    if first_hit_offset is not None:
        cutoff = min(cutoff, _offset(first_hit_offset, "first_hit_offset") - 1)
    for offset in range(1, cutoff + 1):
        if offset >= len(flags):
            return FlagHistory("unknown", None, "window_end", cutoff)
        flag = flags[offset]
        if flag is None:
            return FlagHistory("unknown", None, "missing_before_trigger", cutoff)
        if not isinstance(flag, bool):
            raise ValueError("flags must contain bool or None")
        if flag:
            return FlagHistory("triggered", offset, None, cutoff)
    return FlagHistory("all_false", None, None, cutoff)


def previous_completed_week_signal(common_calendar_dates: Sequence[date], closes: Sequence[Price], t0_index: int) -> bool | None:
    """Previous completed weekly close > SMA10 > prior SMA10, all strict.

    The t0 ISO week is excluded even on Friday. The calendar's first partial
    week is invalid. Ten-week MA comparison needs eleven consecutive valid
    observed trading weeks; no-trade holiday weeks are not invented.
    """
    t0_index = _offset(t0_index, "t0_index", minimum=0)
    if len(common_calendar_dates) != len(closes) or t0_index >= len(closes):
        raise ValueError("dates and closes must have equal length and t0_index must be in range")
    if any(a >= b for a, b in zip(common_calendar_dates, common_calendar_dates[1:])):
        raise ValueError("calendar dates must be strictly increasing")
    t0_date = common_calendar_dates[t0_index]
    current_monday = t0_date - timedelta(days=t0_date.weekday())
    weekly: list[Price] = []
    week: date | None = None
    week_valid = False
    final_close: Price = None
    for index, day in enumerate(common_calendar_dates[:t0_index]):
        if day >= current_monday:
            break
        monday = day - timedelta(days=day.weekday())
        if monday != week:
            if week is not None:
                weekly.append(final_close if week_valid else None)
            week = monday
            week_valid = monday >= common_calendar_dates[0]
        close = closes[index]
        week_valid = week_valid and _valid(close)
        final_close = close
    if week is not None:
        weekly.append(final_close if week_valid else None)
    recent = weekly[-11:]
    if len(recent) < 11 or any(value is None for value in recent):
        return None
    observed = [value for value in recent if value is not None]
    current_ma = math.fsum(observed[1:]) / 10
    prior_ma = math.fsum(observed[:-1]) / 10
    return observed[-1] > current_ma and current_ma > prior_ma


@dataclass(frozen=True)
class ConfirmedPivot:
    extreme_index: int
    confirmed_index: int
    price: float
    extreme_date: date
    confirmed_at: date


def confirmed_pivot_view(pivots: Sequence[tuple[int, int, float]], source_dates: Sequence[date], as_of: date) -> tuple[ConfirmedPivot, ...]:
    """Filter explicit legacy triples by confirmation date; never regenerate."""
    if any(a >= b for a, b in zip(source_dates, source_dates[1:])):
        raise ValueError("source_dates must be strictly increasing")
    result: list[ConfirmedPivot] = []
    for extreme, confirmed, price in pivots:
        extreme = _offset(extreme, "extreme_index", minimum=0)
        confirmed = _offset(confirmed, "confirmed_index", minimum=0)
        if not extreme <= confirmed < len(source_dates):
            raise ValueError("pivot indexes must satisfy 0 <= extreme <= confirmed < len(source_dates)")
        if not _valid(price):
            raise ValueError("pivot price must be finite and positive")
        if source_dates[confirmed] <= as_of:
            result.append(ConfirmedPivot(extreme, confirmed, price, source_dates[extreme], source_dates[confirmed]))
    return tuple(result)

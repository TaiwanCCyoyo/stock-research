"""Shared time-aware growth metrics for retrospective wave observations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date
from typing import Any, Literal, TypedDict, TypeGuard

YEAR_DAYS = 365.25
GROWTH_SCHEMA = "wave-growth.v1"
THRESHOLD_TOLERANCE_PCT = 1e-9
Eligibility = Literal["eligible", "below-threshold", "unknown"]


class GrowthMetric(TypedDict):
    schema: str
    startDate: str | None
    observationDate: str | None
    yearDays: float
    elapsedDays: int | None
    elapsedYears: float | None
    totalGainPct: float | None
    annualizedGainPct: float | None
    sizingGainPct: float | None
    basis: Literal["actual", "annualized", "unknown"]
    reason: str | None


def _finite_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def wave_gain(
    start_date: str | None,
    observation_date: str | None,
    gain_pct: float | None,
    left_censored: bool = False,
) -> GrowthMetric:
    """Calculate actual short-duration or annualized long-duration growth.

    ``gain_pct`` uses percentage points (for example, 1290 means 1290%).
    Left-censored starts retain their known total return but cannot support a
    time-adjusted comparison because the true elapsed duration is unknown.
    """
    total_gain = float(gain_pct) if _finite_number(gain_pct) and gain_pct >= -100 else None
    start = _parse_date(start_date)
    observation = _parse_date(observation_date)
    elapsed_days = (observation - start).days if start is not None and observation is not None else None
    if elapsed_days is not None and elapsed_days < 0:
        elapsed_days = None
    elapsed_years = elapsed_days / YEAR_DAYS if elapsed_days is not None else None

    reason: str | None = None
    if total_gain is None:
        reason = "unknown-gain"
    elif elapsed_days is None:
        reason = "invalid-interval"
    elif left_censored:
        reason = "left-censored-start"

    annualized: float | None = None
    sizing_gain: float | None = None
    basis: Literal["actual", "annualized", "unknown"] = "unknown"
    if reason is None and total_gain is not None and elapsed_years is not None:
        if elapsed_years < 1:
            sizing_gain = total_gain
            basis = "actual"
        else:
            annualized = -100.0 if total_gain == -100 else 100 * math.expm1(math.log1p(total_gain / 100) / elapsed_years)
            sizing_gain = annualized
            basis = "annualized"

    return {
        "schema": GROWTH_SCHEMA,
        "startDate": start_date if isinstance(start_date, str) else None,
        "observationDate": observation_date if isinstance(observation_date, str) else None,
        "yearDays": YEAR_DAYS,
        "elapsedDays": elapsed_days,
        "elapsedYears": elapsed_years,
        "totalGainPct": total_gain,
        "annualizedGainPct": annualized,
        "sizingGainPct": sizing_gain,
        "basis": basis,
        "reason": reason,
    }


def classify_growth(metric: Mapping[str, Any], threshold_pct: float = 100) -> Eligibility:
    """Classify only known metrics; unknown values never count as misses."""
    if not _finite_number(threshold_pct) or threshold_pct <= 0:
        raise ValueError("threshold_pct must be finite and positive")
    value = metric.get("sizingGainPct")
    if metric.get("basis") == "unknown" or not _finite_number(value):
        return "unknown"
    return "eligible" if value >= threshold_pct - THRESHOLD_TOLERANCE_PCT else "below-threshold"

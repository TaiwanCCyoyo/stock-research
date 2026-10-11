"""Explicit as-of multiplicative signal history; never share/cash entitlement accounting.

This is a named draft signal policy, not the loader's legacy five-bar dividend window.
It applies a source-resolved factor once to pre-effective OHLC only after both its
effective date and supplied availability. It never derives a factor from a price move,
infers an absent event list is complete, or uses the factor to infer a cash/share right.
No file, source or market lookup is performed here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd

POLICY_ID = "asof-multiplicative-signal-v1-draft"
OHLC = ("Open", "High", "Low", "Close")


class SignalProjectionError(ValueError):
    """A required effective/availability/factor fact is unresolved."""


def instant(value: object) -> pd.Timestamp:
    try:
        stamp = pd.Timestamp(value)
    except (ValueError, TypeError) as error:
        raise SignalProjectionError("invalid aware availability") from error
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise SignalProjectionError("explicit aware availability is required")
    return stamp


def _multiply(value: Any, factor: Decimal) -> Any:
    if pd.isna(value):
        return value
    result = float(Decimal(str(value)) * factor)
    if not math.isfinite(result) or result <= 0:
        raise SignalProjectionError("signal factor product is outside finite positive numeric range")
    return result


@dataclass(frozen=True)
class Adjustment:
    event_id: str
    code: str
    effective_on: date
    prior_price_multiplier: Decimal | None
    available_at: datetime | None
    source_id: str


@dataclass(frozen=True)
class FactorCoverage:
    """Supplier's resolved-event completeness claim, not verified source certification.

    Applies to one continuous security history identified by code. The caller must
    resolve vintage/revision conflicts upstream and retain evidence for this assertion.
    """

    code: str
    effective_from: date
    effective_through: date
    available_at: datetime
    source_id: str
    complete: bool


def project_signal_history(
    raw: pd.DataFrame,
    adjustments: Sequence[Adjustment],
    coverage: Sequence[FactorCoverage],
    *,
    decision_cutoff: datetime,
    raw_basis: str,
    continuous_cross_market_codes: frozenset[str] = frozenset(),
) -> pd.DataFrame:
    """Build one as-of history, NOT a multi-date hindsight-adjusted feature table.

    Past rows can be restated using facts known *at this cutoff*. They must not be
    used to decide on those past dates. Rebuild the applicable event prefix at each
    decision cutoff (or use an equivalently tested causal cache). No rounding, volume
    adjustment, price filling or share/cash-event fabrication occurs.
    """
    cutoff = instant(decision_cutoff)
    local_day = cutoff.tz_convert("Asia/Taipei").date()
    required = {"Market", "Code", "Date", "Volume", "available_at", "source_id", *OHLC}
    if raw_basis != "raw_observed_not_adjusted" or not required.issubset(raw.columns) or raw.empty:
        raise SignalProjectionError("explicit nonempty raw observed frame required")
    out = raw.copy(deep=True).reset_index(drop=True)
    dates = pd.to_datetime(out["Date"], errors="raise")
    if dates.isna().any() or dates.dt.tz is not None or (dates != dates.dt.normalize()).any():
        raise SignalProjectionError("Date must be an unambiguous session date")
    if (dates.dt.date > local_day).any():
        raise SignalProjectionError("future price rows must not enter an as-of history")
    if out.duplicated(["Code", "Date"]).any():
        raise SignalProjectionError("duplicate code/date including cross-market overlap")
    for name in ("Code", "Market", "source_id"):
        if not out[name].map(lambda value: isinstance(value, str) and bool(value.strip())).all():
            raise SignalProjectionError(f"missing {name} identity")
    for code, group in out.groupby("Code", sort=False):
        if group["Market"].nunique() > 1 and code not in continuous_cross_market_codes:
            raise SignalProjectionError("cross-market history needs explicit continuity evidence")
    available = out["available_at"].map(instant)
    if (available > cutoff).any():
        raise SignalProjectionError("raw price availability is after decision cutoff")
    out["Date"] = dates
    out["available_at"] = available
    # Missing prices remain missing. Malformed/zero prices never turn into signal zero.
    for column in OHLC:
        for value in out[column].dropna():
            number = Decimal(str(value))
            if not number.is_finite() or number <= 0:
                raise SignalProjectionError("raw OHLC must be positive finite or missing")

    by_code: dict[str, FactorCoverage] = {}
    for item in coverage:
        if item.code in by_code:
            raise SignalProjectionError("duplicate coverage; resolve intervals explicitly")
        by_code[item.code] = item
    for code, group in out.groupby("Code", sort=False):
        claim = by_code.get(code)
        first = group["Date"].min().date()
        if (
            claim is None
            or claim.complete is not True
            or not claim.source_id.strip()
            or claim.effective_from > first
            or claim.effective_through < local_day
            or instant(claim.available_at) > cutoff
        ):
            raise SignalProjectionError(f"resolved factor coverage not established: {code}")

    relevant: list[Adjustment] = []
    for event in adjustments:
        if event.code not in by_code or event.effective_on > local_day:
            continue
        mask = (out["Code"] == event.code) & (dates.dt.date < event.effective_on)
        if not mask.any():
            continue
        factor = event.prior_price_multiplier
        if (
            not event.event_id.strip()
            or not event.source_id.strip()
            or factor is None
            or not factor.is_finite()
            or factor <= 0
            or event.available_at is None
            or instant(event.available_at) > cutoff
        ):
            raise SignalProjectionError(f"applicable adjustment is unresolved: {event.event_id}")
        relevant.append(event)
    if len({item.event_id for item in relevant}) != len(relevant) or len({(item.code, item.effective_on) for item in relevant}) != len(relevant):
        raise SignalProjectionError("overlapping adjustment/revision factors need upstream resolution")

    event_ids: list[str] = []
    for event in sorted(relevant, key=lambda item: (item.effective_on, item.code, item.event_id)):
        assert event.prior_price_multiplier is not None and event.available_at is not None
        multiplier = event.prior_price_multiplier
        mask = (out["Code"] == event.code) & (dates.dt.date < event.effective_on)
        for column in OHLC:
            out.loc[mask, column] = out.loc[mask, column].map(lambda value: _multiply(value, multiplier))
        event_at = instant(event.available_at)
        out.loc[mask, "available_at"] = out.loc[mask, "available_at"].map(lambda stamp: max(stamp, event_at))
        out.loc[mask, "source_id"] = out.loc[mask, "source_id"].map(lambda source: f"{source}|{event.source_id}|{event.event_id}")
        event_ids.append(event.event_id)
    out.attrs["signal_projection"] = {
        "policy_id": POLICY_ID,
        "decision_cutoff": cutoff.isoformat(),
        "applied_event_ids": event_ids,
        "coverage_source_ids": [by_code[code].source_id for code in sorted(out["Code"].unique())],
        "availability_basis": "explicit input claims; not independently certified by this helper",
        "economic_entitlements": "not_inferred",
    }
    return out

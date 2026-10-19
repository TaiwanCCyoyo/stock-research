"""Source-admitted economic entitlements for fixed annual-rotation selections.

This separately versioned kernel preserves v1's endpoint and cost conventions.
Entitlement terms must come from the caller's evidence admission; price factors
are quality diagnostics and never a source of economic share quantities.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.price_basis import prepare_prices

LOGGER = logging.getLogger(__name__)
VERSION = "annual-rotation.v2"
SUPPORTED_SOURCE_EVENTS = frozenset({
    "CASH_DIVIDEND",
    "EX_RIGHT",
    "EX_RIGHT_AND_DIVIDEND",
    "CASH_CAPITAL_REDUCTION",
    "LOSS_OFFSET_CAPITAL_REDUCTION",
    "CAPITAL_REDUCTION",
    "ETF_SPLIT",
    "ETF_REVERSE_SPLIT",
})


def _iso_date(value: str, label: str) -> pd.Timestamp:
    try:
        parsed = dt.date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be an ISO daily date") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{label} must be an ISO daily date")
    result = pd.Timestamp(parsed)
    if not isinstance(result, pd.Timestamp):
        raise ValueError(f"{label} must not be NaT")
    return result


@dataclass(frozen=True)
class Entitlement:
    """Explicit terms per pre-event share, with source identifiers for audit.

    ``announced_date`` is the original scheduled ex-date in the source action,
    never a notice's publication date. ``effective_date`` is the caller-admitted
    application date with an actual valid quote when share quantities change.
    ``source_event_type`` binds that original action exactly; absent source rows
    are permitted only for evidenced share-only transformations.
    """

    code: str
    effective_date: str
    announced_date: str
    share_multiplier: float = 1.0
    cash_per_old_share: float = 0.0
    rights_per_old_share: float = 0.0
    subscription_price: float | None = None
    evidence_ids: tuple[str, ...] = ()
    kind: str = "ENTITLEMENT"
    source_event_type: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip() or not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("nonempty entitlement code and kind required")
        _iso_date(self.effective_date, "effective_date")
        _iso_date(self.announced_date, "announced_date")
        for label in ("share_multiplier", "cash_per_old_share", "rights_per_old_share"):
            value = getattr(self, label)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not np.isfinite(value) or value < 0:
                raise ValueError(f"{label} must be finite and nonnegative")
        if self.share_multiplier <= 0:
            raise ValueError("share_multiplier must be positive")
        if self.subscription_price is not None and (
            isinstance(self.subscription_price, bool)
            or not isinstance(self.subscription_price, (float, int))
            or not np.isfinite(self.subscription_price)
            or self.subscription_price < 0
        ):
            raise ValueError("subscription_price must be finite and nonnegative")
        if not isinstance(self.evidence_ids, tuple) or any(not isinstance(item, str) or not item.strip() for item in self.evidence_ids):
            raise ValueError("evidence_ids must be a tuple of nonempty identifiers")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("duplicate evidence identifiers")
        if self.rights_per_old_share > 0 and (self.subscription_price is None or not self.evidence_ids):
            raise ValueError("rights require a subscription price and evidence identifiers")
        if self.source_event_type is not None and self.source_event_type not in SUPPORTED_SOURCE_EVENTS:
            raise ValueError("unsupported entitlement source_event_type")


def _source_metadata(event: pd.Series) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in event.items():
        if isinstance(value, pd.Timestamp):
            result[str(key)] = value.isoformat()
        else:
            scalar = value.item() if isinstance(value, np.generic) else value
            missing = scalar is pd.NA or scalar is pd.NaT or isinstance(scalar, float) and not math.isfinite(scalar)
            result[str(key)] = None if missing else scalar
    return result


def _quality_diagnostics(
    entitlement: Entitlement, sources: pd.DataFrame, frame: pd.DataFrame, day: pd.Timestamp, *, previous_close: float | None = None
) -> list[dict[str, Any]]:
    """Explain a jump only from stated source factors or exact share-only terms."""
    factors: list[tuple[str, float]] = []
    if entitlement.cash_per_old_share == 0 and entitlement.rights_per_old_share == 0:
        factors.append(("reciprocal_exact_share_multiplier", 1 / entitlement.share_multiplier))
    for _, source in sources.iterrows():
        try:
            factor = float(source.price_factor)
        except (ValueError, TypeError):
            continue
        if math.isfinite(factor) and factor > 0:
            factors.append(("source_price_factor", factor))
    position = int(frame.index.get_indexer([day])[0])
    previous = previous_close if previous_close is not None else float(frame.RawClose.iloc[position - 1]) if position else np.nan
    close = float(frame.loc[day, "RawClose"])
    change = close / previous - 1 if np.isfinite(previous) and previous > 0 and np.isfinite(close) and close > 0 else np.nan
    return [
        {
            "source": source,
            "diagnostic_only": True,
            "factor": factor,
            "raw_close_change": float(change) if np.isfinite(change) else None,
            "residual": float((1 + change) / factor - 1) if np.isfinite(change) else None,
            "explains_jump": bool(np.isfinite(change) and (factor - 1) * change > 0 and abs((1 + change) / factor - 1) < 0.4),
        }
        for source, factor in factors
    ]


def _theoretical_terms_diagnostic(
    *,
    anchor_day: pd.Timestamp,
    day: pd.Timestamp,
    previous: float,
    close: float,
    share: float,
    cash: float,
    rights: float = 0,
    subscription: float = 0,
    context: str = "recovery",
) -> dict[str, Any]:
    """Diagnose a quote from explicit terms, without changing economic units.

    The theoretical ex-right ratio is independent of the holder's rights
    scenario. It expresses mechanical dilution, not an exercise assumption.
    """
    denominator = previous * (share + rights)
    factor = (previous - cash + rights * subscription) / denominator if math.isfinite(denominator) and denominator > 0 else np.nan
    valid = math.isfinite(factor) and factor > 0
    change = close / previous - 1
    residual = (1 + change) / factor - 1 if valid else None
    source = f"{context}_theoretical_ex_right_terms" if rights > 0 else f"{context}_cash_share_terms" if cash > 0 else f"{context}_exact_share_terms"
    return {
        "source": source,
        "diagnostic_only": True,
        "date": str(day.date()),
        "anchor_date": str(anchor_day.date()),
        "anchor_raw_close": previous,
        "factor": factor if math.isfinite(factor) else None,
        "factor_valid": valid,
        "raw_close_change": change,
        "residual": residual,
        "explains_jump": bool(valid and (factor - 1) * change > 0 and residual is not None and abs(residual) < 0.4),
    }


def _native_terms_contradict(frame: pd.DataFrame, day: pd.Timestamp, *, share: float, cash: float, field: str = "Close") -> dict[str, Any] | None:
    """Diagnose a producer cash or exact split action against the last observed close.

    Returns the diagnostic when the observed close contradicts the action grossly
    (residual of 40% or more), otherwise None; no observed anchor means no check.
    """
    position = int(frame.index.get_indexer([day])[0])
    prior = frame.iloc[:position]
    observed = prior.loc[prior.Quality.astype(bool) & np.isfinite(prior.RawClose.astype(float)) & prior.RawClose.astype(float).gt(0)]
    close = float(frame.loc[day, f"Raw{field}"])  # the exit-day Open for an open exit
    if not len(observed) or not bool(frame.loc[day, "Quality"]) or not np.isfinite(close) or close <= 0:
        return None
    diagnostic = _theoretical_terms_diagnostic(
        anchor_day=cast(pd.Timestamp, observed.index[-1]),
        day=day,
        previous=float(observed.RawClose.iloc[-1]),
        close=close,
        share=share,
        cash=cash,
        context="native_action",
    )
    residual = diagnostic["residual"]
    consistent = bool(diagnostic["factor_valid"] and residual is not None and abs(residual) < 0.4)
    return None if consistent else diagnostic


def _require_source_factor_explanation(diagnostic: dict[str, Any], source_diagnostics: list[dict[str, Any]]) -> None:
    source_explains = any(value["source"] == "source_price_factor" and value["explains_jump"] for value in source_diagnostics)
    diagnostic["source_factor_explains_jump"] = source_explains
    diagnostic["explains_jump"] = diagnostic["explains_jump"] and source_explains


def economic_path_v2(
    raw: pd.DataFrame,
    actions: pd.DataFrame,
    calendar: pd.DatetimeIndex,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    start_field: str = "Open",
    end_field: str = "Open",
    commission: float = 0.0,
    sell_tax: float = 0.0,
    slippage: float = 0.0,
    split_ratios: Mapping[str, float] | None = None,
    known_halts: set[str] | None = None,
    unavailable_days: Mapping[str, str] | None = None,
    entitlements: Sequence[Entitlement] = (),
    rights_scenario: str = "lapse",
    entry_cost: bool = True,
    exit_cost: bool = True,
) -> dict[str, Any]:
    """Model stated rights scenarios; incomplete daily marks stay explicit.

    Only H/N evidence can permit an all-NaN OHLC row to carry its last mark; the
    caller must normalize official null sentinels first. Valid observations
    always win. Carried marks never provide event-date reinvestment prices,
    execution endpoints, or share-quantity changes. ``realize`` values rights at
    their positive intrinsic value; it is not an actual subscription or a bound.
    """
    if start_field not in {"Open", "Close"} or end_field not in {"Open", "Close"}:
        raise ValueError("endpoint field must be Open or Close")
    if start >= end or start not in calendar or end not in calendar:
        raise ValueError("ordered calendar endpoints required")
    if any(not np.isfinite(value) or value < 0 or value >= 1 for value in (commission, sell_tax, slippage)):
        raise ValueError("cost fractions must be finite in [0,1)")
    if commission + sell_tax >= 1:
        raise ValueError("combined exit costs must be below proceeds")
    if rights_scenario not in {"lapse", "realize"}:
        raise ValueError("rights_scenario must be lapse or realize")
    if raw.empty:
        raise ValueError("nonempty issuer history required")
    days = calendar[(calendar >= start) & (calendar <= end)]
    code = str(raw.Code.iloc[0])
    events = actions.loc[actions.code.astype(str).eq(code) & pd.to_datetime(actions.ex_date).between(start, end)].copy().reset_index(drop=True)
    event_dates = pd.to_datetime(events.ex_date)
    active = [item for item in entitlements if item.code == code and start < pd.Timestamp(item.effective_date) <= end]
    unknowns: list[str] = []
    bindings: dict[pd.Timestamp, tuple[Entitlement, pd.DataFrame]] = {}
    replaced: set[int] = set()
    for item in active:
        day = _iso_date(item.effective_date, "effective_date")
        announced = pd.Timestamp(item.announced_date)
        matches = events.loc[event_dates.eq(announced) & events.event_type.eq(item.source_event_type)]
        if announced <= start < day:
            unknowns.append(f"{item.effective_date}:ownership_before_entry_unresolved")
        if day not in days:
            unknowns.append(f"{item.effective_date}:noncalendar_entitlement")
        if day in bindings:
            unknowns.append(f"{item.effective_date}:duplicate_or_conflicting_entitlements")
        if len(matches) > 1 or replaced.intersection(matches.index):
            unknowns.append(f"{item.effective_date}:ambiguous_override_actions")
        if matches.empty and (item.cash_per_old_share > 0 or item.rights_per_old_share > 0):
            unknowns.append(f"{item.effective_date}:missing_override_action")
        if matches.empty and not item.evidence_ids:
            unknowns.append(f"{item.effective_date}:synthetic_share_entitlement_requires_evidence")
        if any(date not in days for date in pd.to_datetime(matches.ex_date)) and not item.evidence_ids:
            unknowns.append(f"{item.effective_date}:noncalendar_override_requires_evidence")
        bindings[day] = (item, matches)
        replaced.update(matches.index)
    # Removed rows retain their complete factual metadata in the applied audit.
    # No synthetic factor is written into an action supplied by the caller.
    remaining = events.drop(index=list(replaced))
    quotes = raw.loc[raw.Date.between(start, end)]
    frame = prepare_prices(quotes, remaining, days, basis="raw", cutoff=end)
    diagnostics: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for day, (item, sources) in bindings.items():
        if day not in days:
            continue
        diagnostic = _quality_diagnostics(item, sources, frame, day)
        diagnostics[day] = diagnostic
        if frame.loc[day, "quality_reason"] == "unexplained_raw_jump":
            explained = any(row["explains_jump"] for row in diagnostic)
            position = int(frame.index.get_indexer([day])[0])
            anchor_day = cast(pd.Timestamp, frame.index[position - 1])
            terms_diagnostic = _theoretical_terms_diagnostic(
                anchor_day=anchor_day,
                day=day,
                previous=float(frame.RawClose.iloc[position - 1]),
                close=float(frame.loc[day, "RawClose"]),
                share=item.share_multiplier,
                cash=item.cash_per_old_share,
                rights=item.rights_per_old_share,
                subscription=item.subscription_price or 0,
                context="event",
            )
            if item.rights_per_old_share > 0:
                _require_source_factor_explanation(terms_diagnostic, diagnostic)
            else:
                # A producer factor can corroborate explicit economic terms;
                # it cannot override contradictory share or cash quantities.
                terms_diagnostic["explains_jump"] = terms_diagnostic["explains_jump"] and explained
            diagnostic.append(terms_diagnostic)
            explained = bool(terms_diagnostic["explains_jump"])
            LOGGER.debug("Entitlement quality code=%s date=%s diagnostic=%s", code, day.date(), terms_diagnostic)
            if explained:
                frame.loc[day, "Quality"] = True
                frame.loc[day, "quality_reason"] = None
        elif bool(frame.loc[day, "Quality"]) and (day < end or end_field == "Close" or (item.share_multiplier == 1 and item.rights_per_old_share == 0)):
            # A share or rights change on an open-exit day is already ambiguous; a cash-only
            # entitlement credited at an open exit is checked against the exit open.
            # Below the jump threshold the terms are still applied to holdings, so an
            # observed quote that contradicts them grossly (e.g. a halving share
            # multiplier on a rising close) keeps the path unknown. Direction is not
            # required here: ordinary noise may move a small factor either way.
            # Compare with the last observed close, so a first quote after an admitted
            # H/N carry is checked against the price before the gap.
            position = int(frame.index.get_indexer([day])[0])
            prior = frame.iloc[:position]
            observed = prior.loc[prior.Quality.astype(bool) & np.isfinite(prior.RawClose.astype(float)) & prior.RawClose.astype(float).gt(0)]
            previous = float(observed.RawClose.iloc[-1]) if len(observed) else np.nan
            if np.isfinite(previous):
                terms_diagnostic = _theoretical_terms_diagnostic(
                    anchor_day=cast(pd.Timestamp, observed.index[-1]),
                    day=day,
                    previous=previous,
                    close=float(frame.loc[day, "RawOpen" if day == end and end_field == "Open" else "RawClose"]),
                    share=item.share_multiplier,
                    cash=item.cash_per_old_share,
                    rights=item.rights_per_old_share,
                    subscription=item.subscription_price or 0,
                    context="event",
                )
                residual = terms_diagnostic["residual"]
                terms_diagnostic["consistent_with_terms"] = bool(terms_diagnostic["factor_valid"] and residual is not None and abs(residual) < 0.4)
                diagnostic.append(terms_diagnostic)
                if not terms_diagnostic["consistent_with_terms"]:
                    unknowns.append(f"{day.date()}:entitlement_terms_contradict_observed_quote")
    availability = {day: "H" for day in known_halts or set()}
    availability.update(unavailable_days or {})
    carried: set[pd.Timestamp] = set()
    for raw_day, row in frame.iterrows():
        day = cast(pd.Timestamp, raw_day)
        prices = np.array([row.RawOpen, row.RawHigh, row.RawLow, row.RawClose], dtype=float)
        no_ohlc = bool(np.isnan(prices).all())
        permitted = availability.get(str(day.date())) in {"H", "N"} and no_ohlc and row.quality_reason in {"missing_official_quote", "invalid_ohlc"}
        if not bool(row.Quality):
            if permitted:
                carried.add(day)
            else:
                unknowns.append(f"{day.date()}:{row.quality_reason}")
    # pct_change(fill_method=None) deliberately leaves the session after a
    # missing quote untested. Recheck only bridges over admitted H/N carry;
    # an arbitrary action or source factor alone is never an explanation.
    recovery_diagnostics: dict[pd.Timestamp, dict[str, Any]] = {}
    previous_observed_day: pd.Timestamp | None = None
    previous_observed_close: float | None = None
    after_carry = False
    for raw_day, row in frame.iterrows():
        day = cast(pd.Timestamp, raw_day)
        if day in carried:
            after_carry = True
            binding = bindings.get(day)
            if binding is not None and binding[0].share_multiplier != 1:
                unknowns.append(f"{day.date()}:share_change_requires_observed_effective_quote")
            continue
        if not bool(row.Quality):
            after_carry = False
            continue
        close = float(row.RawClose)
        if after_carry and previous_observed_close is not None and previous_observed_day is not None and abs(close / previous_observed_close - 1) >= 0.4:
            bridge_diagnostic: dict[str, Any] | None = None
            binding = bindings.get(day)
            if binding is not None:
                item, sources = binding
                bridge_diagnostic = _theoretical_terms_diagnostic(
                    anchor_day=previous_observed_day,
                    day=day,
                    previous=previous_observed_close,
                    close=close,
                    share=item.share_multiplier,
                    cash=item.cash_per_old_share,
                    rights=item.rights_per_old_share,
                    subscription=item.subscription_price or 0,
                )
                if item.rights_per_old_share > 0:
                    source_diagnostics = _quality_diagnostics(item, sources, frame, day, previous_close=previous_observed_close)
                    _require_source_factor_explanation(bridge_diagnostic, source_diagnostics)
                diagnostics[day].append(bridge_diagnostic)
            else:
                current = remaining.loc[pd.to_datetime(remaining.ex_date).eq(day)]
                if len(current) == 1:
                    event = current.iloc[0]
                    share, cash = 1.0, 0.0
                    try:
                        if event.event_type == "CASH_DIVIDEND":
                            cash = float(event.cash_dividend_estimate)
                        elif event.event_type in {"ETF_SPLIT", "ETF_REVERSE_SPLIT"}:
                            share = float((split_ratios or {}).get(str(day.date()), np.nan))
                        else:
                            share = np.nan
                    except (TypeError, ValueError):
                        share = np.nan
                    if math.isfinite(share) and share > 0 and math.isfinite(cash) and cash >= 0:
                        bridge_diagnostic = _theoretical_terms_diagnostic(
                            anchor_day=previous_observed_day, day=day, previous=previous_observed_close, close=close, share=share, cash=cash
                        )
            if bridge_diagnostic is not None:
                recovery_diagnostics[day] = bridge_diagnostic
            LOGGER.debug("Recovery quality code=%s date=%s diagnostic=%s", code, day.date(), bridge_diagnostic)
            if bridge_diagnostic is None or not bridge_diagnostic["explains_jump"]:
                reason = (
                    "invalid_recovery_economic_factor"
                    if bridge_diagnostic is not None and not bridge_diagnostic["factor_valid"]
                    else "unexplained_raw_jump_after_carry"
                )
                unknowns.append(f"{day.date()}:{reason}")
        previous_observed_day, previous_observed_close = day, close
        after_carry = False
    entry = float(frame.loc[start, f"Raw{start_field}"])
    exit_price = float(frame.loc[end, f"Raw{end_field}"])
    if start in carried or end in carried or not np.isfinite(entry) or not np.isfinite(exit_price) or min(entry, exit_price) <= 0:
        unknowns.append("missing_endpoint_price")
    marks: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []

    def unknown_result() -> dict[str, Any]:
        LOGGER.debug("Unresolved v2 path start=%s end=%s reasons=%s", start, end, unknowns)
        return {
            "status": "unknown",
            "reasons": unknowns,
            "raw_entry": entry if np.isfinite(entry) and entry > 0 else None,
            "raw_exit": exit_price if np.isfinite(exit_price) and exit_price > 0 else None,
            "gross_multiplier": None,
            "net_multiplier": None,
            "marks": marks,
            "events": applied,
            "complete_equity": False,
            "carried_days": len(carried),
            "recovery_quality_diagnostics": list(recovery_diagnostics.values()),
        }

    if unknowns:
        return unknown_result()
    by_day: dict[pd.Timestamp, pd.DataFrame] = dict(tuple(remaining.groupby(pd.to_datetime(remaining.ex_date))))
    noncalendar = [str(day.date()) for day in by_day if day not in days and day > start]
    if noncalendar:
        unknowns.extend(f"{day}:noncalendar_action" for day in noncalendar)
        return unknown_result()
    gross_units = 1 / entry
    net_units = 1 / (entry * (1 + slippage) * (1 + commission)) if entry_cost else 1 / entry
    last_mark = entry
    for raw_day, row in frame.iterrows():
        day = cast(pd.Timestamp, raw_day)
        cash_gross = cash_net = 0.0
        day_events = by_day.get(day)
        binding = bindings.get(day)
        if day > start and binding is not None:
            item, sources = binding
            if day_events is not None:
                unknowns.append(f"{day.date()}:ambiguous_same_day_actions")
                break
            if day in carried and item.share_multiplier != 1:
                unknowns.append(f"{day.date()}:share_change_requires_observed_effective_quote")
                break
            if day == end and end_field == "Open" and (item.share_multiplier != 1 or item.rights_per_old_share > 0):
                unknowns.append(f"{day.date()}:ambiguous_open_exit_entitlement")
                break
            close = float(row.RawClose)
            requires_close = item.cash_per_old_share > 0 or rights_scenario == "realize" and item.rights_per_old_share > 0
            exit_cash_only = day == end and end_field == "Open"
            if requires_close and not exit_cash_only and (day in carried or not bool(row.Quality) or not np.isfinite(close) or close <= 0):
                unknowns.append(f"{day.date()}:missing_entitlement_reinvestment_close")
                break
            rights_value = (
                item.rights_per_old_share * max(0.0, close - cast(float, item.subscription_price))
                if rights_scenario == "realize" and item.rights_per_old_share > 0
                else 0.0
            )
            cash = item.cash_per_old_share + rights_value
            old_gross, old_net = gross_units, net_units
            gross_units *= item.share_multiplier
            net_units *= item.share_multiplier
            if exit_cash_only:
                cash_gross, cash_net = old_gross * cash, old_net * cash
            elif cash > 0:
                gross_units += old_gross * cash / close
                net_units += old_net * cash / (close * (1 + commission))
            applied.append({
                "date": item.effective_date,
                "type": item.kind,
                "announced_date": item.announced_date,
                "source_event_type": item.source_event_type,
                "share_multiplier": item.share_multiplier,
                "cash_per_old_share": item.cash_per_old_share,
                "rights_per_old_share": item.rights_per_old_share,
                "subscription_price": item.subscription_price,
                "rights_scenario": rights_scenario,
                "rights_value_per_old_share": rights_value,
                "evidence_ids": list(item.evidence_ids),
                "source_actions": [_source_metadata(source) for _, source in sources.iterrows()],
                "quality_diagnostics": diagnostics[day],
            })
        elif day > start and day_events is not None:
            if len(day_events) != 1:
                unknowns.append(f"{day.date()}:ambiguous_same_day_actions")
                break
            event = day_events.iloc[0]
            kind = str(event.event_type)
            audit: dict[str, Any] = {"date": str(day.date()), "type": kind, "source_actions": [_source_metadata(event)]}
            if day in recovery_diagnostics:
                audit["recovery_quality_diagnostic"] = recovery_diagnostics[day]
            if kind == "CASH_DIVIDEND":
                dividend = float(event.cash_dividend_estimate)
                if not np.isfinite(dividend) or dividend < 0:
                    unknowns.append(f"{day.date()}:missing_or_negative_cash_estimate")
                    break
                if day == end and end_field == "Open":
                    if (contradiction := _native_terms_contradict(frame, day, share=1.0, cash=dividend, field="Open")) is not None:
                        audit["quality_diagnostic"] = contradiction
                        unknowns.append(f"{day.date()}:native_action_contradicts_observed_quote")
                        break
                    cash_gross, cash_net = gross_units * dividend, net_units * dividend
                else:
                    if (contradiction := _native_terms_contradict(frame, day, share=1.0, cash=dividend)) is not None:
                        audit["quality_diagnostic"] = contradiction
                        unknowns.append(f"{day.date()}:native_action_contradicts_observed_quote")
                        break
                    close = float(row.RawClose)
                    if day in carried or not bool(row.Quality) or not np.isfinite(close) or close <= 0:
                        unknowns.append(f"{day.date()}:missing_dividend_reinvestment_close")
                        break
                    gross_units *= 1 + dividend / close
                    net_units *= 1 + dividend / (close * (1 + commission))
                audit["cash_per_unit_estimate"] = dividend
            elif kind in {"ETF_SPLIT", "ETF_REVERSE_SPLIT"}:
                ratio = (split_ratios or {}).get(str(day.date()))
                if ratio is None or not np.isfinite(ratio) or ratio <= 0:
                    unknowns.append(f"{day.date()}:missing_exact_share_ratio")
                    break
                exit_open = day == end and end_field == "Open"
                if _native_terms_contradict(frame, day, share=ratio, cash=0.0, field="Open" if exit_open else "Close") is not None:
                    unknowns.append(f"{day.date()}:native_action_contradicts_observed_quote")
                    break
                gross_units *= ratio
                net_units *= ratio
                audit["exact_share_ratio"] = ratio
            else:
                unknowns.append(f"{day.date()}:unsupported_economic_action:{kind}")
                break
            applied.append(audit)
        mark = last_mark if day in carried else float(row.RawClose)
        last_mark = mark
        if day == end:
            gross_value = gross_units * exit_price + cash_gross
            net_value = net_units * exit_price * ((1 - slippage) * (1 - commission - sell_tax) if exit_cost else 1) + cash_net
        elif day == start and start_field == "Close":
            gross_value, net_value = 1.0, net_units * entry
        else:
            gross_value, net_value = gross_units * mark, net_units * mark
        marks.append({"date": str(day.date()), "gross": gross_value, "net": net_value, "mark_observed": day not in carried})
    if unknowns:
        return unknown_result()
    return {
        "status": "modeled",
        "reasons": [],
        "raw_entry": entry,
        "raw_exit": exit_price,
        "gross_multiplier": marks[-1]["gross"],
        "net_multiplier": marks[-1]["net"],
        "marks": marks,
        "events": applied,
        "complete_equity": not carried,
        "carried_days": len(carried),
        "recovery_quality_diagnostics": list(recovery_diagnostics.values()),
    }

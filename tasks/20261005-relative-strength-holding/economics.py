"""Compose explicitly bound economics using existing leaf account providers.

No source selection, source parsing, pricing inference or parallel ledger lives
here. Execution limits alone never establish supported event economics.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from types import MappingProxyType
from typing import Any

from research_core.chronology import CorporateProvider

LOGGER = logging.getLogger(__name__)
TAIPEI = timezone(timedelta(hours=8))
EventIdentity = tuple[date, str, str]
EventKey = tuple[date, str]


class EconomicBindingError(ValueError):
    """Supplied source-bound identities or economic domains are inconsistent."""


@dataclass(frozen=True)
class BoundCapital:
    event: Any
    factor_id: str


@dataclass(frozen=True)
class BoundShare:
    event: Any
    factor_id: str


@dataclass(frozen=True)
class BoundPaid:
    event: Any
    composer: Callable[..., CorporateProvider]
    limits: Any


@dataclass(frozen=True)
class EconomicBindings:
    cash_package: Any
    capital: tuple[BoundCapital, ...] = ()
    shares: tuple[BoundShare, ...] = ()
    mixed: tuple[BoundShare, ...] = ()
    paid: tuple[BoundPaid, ...] = ()


@dataclass(frozen=True)
class EconomicPlan:
    event_limits: Mapping[EventKey, Any]
    corporate_keys: frozenset[EventKey]
    unsupported: tuple[EventIdentity, ...]
    _build: Callable[[list[dict[str, Any]], list[dict[str, Any]]], Callable[[], CorporateProvider]]

    def new_factory(self, diagnostics: list[dict[str, Any]], subscription_decisions: list[dict[str, Any]]) -> Callable[[], CorporateProvider]:
        """Bind scenario audit sinks; every invocation constructs fresh providers."""
        return self._build(diagnostics, subscription_decisions)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EconomicBindingError(f"{label} must be nonempty text")
    return value


def _day(value: Any) -> date:
    if type(value) is not date:
        raise EconomicBindingError("event key must have a date-only value")
    return value


def _at(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(hours=8):
        raise EconomicBindingError("economic times must be aware +08:00 datetimes")
    return value


def _identity(day: Any, code: Any, identity: Any) -> EventIdentity:
    return _day(day), _text(code, "code"), _text(identity, "event identity")


def prepare_economics(
    modules: Mapping[str, Any],
    bindings: EconomicBindings,
    *,
    factors: Sequence[EventIdentity],
    beginning: datetime,
    ending: datetime,
    initial_limits: Mapping[EventKey, Any],
    payment_delay_days: int = 45,
) -> EconomicPlan:
    """Validate domain removal and return fresh composition factories.

    Caller-supplied initial limits may include named limits-only evidence. Those
    entries affect execution only; they do not remove an unsupported identity.
    """
    required = ("cash_terms", "corporate", "capital_event", "stock_rights", "mixed_rights", "event_limits")
    if any(name not in modules for name in required):
        raise EconomicBindingError("explicit cash/corporate/capital/share/mixed/limits modules required")
    dependencies = MappingProxyType({name: modules[name] for name in required})
    if not isinstance(bindings, EconomicBindings):
        raise EconomicBindingError("explicit EconomicBindings required")
    beginning, ending = _at(beginning), _at(ending)
    if beginning >= ending:
        raise EconomicBindingError("economic coverage beginning must precede ending")
    if type(payment_delay_days) is not int or payment_delay_days not in (45, 90):
        raise EconomicBindingError("payment delay must be 45 or 90 calendar days")
    factor_rows = tuple(_identity(*row) for row in factors)
    factor_keys = [(day, code) for day, code, _identifier in factor_rows]
    if len(set(factor_rows)) != len(factor_rows) or len(set(factor_keys)) != len(factor_keys):
        raise EconomicBindingError("duplicate or colliding factor identities")
    package = bindings.cash_package
    terms = tuple(package.terms)
    cash_keys: set[tuple[str, date]] = set()
    cash_ids: set[str] = set()
    for term in terms:
        key = (_text(term.code, "cash code"), _at(term.entitlement_at).date())
        identifier = _text(term.event_id, "cash event identity")
        if key in cash_keys or identifier in cash_ids:
            raise EconomicBindingError("duplicate cash term or identity")
        cash_keys.add(key)
        cash_ids.add(identifier)
    rights_keys = {(_text(code, "rights code"), date.fromisoformat(day)) for _market, code, day in package.noncash_keys}
    corporate = dependencies["corporate"]
    unbound, boundaries = corporate.event_domains(factor_rows, cash_keys, rights_keys)
    unsupported = set(unbound)
    if len(unsupported) != len(unbound):
        raise EconomicBindingError("duplicate unsupported event identity")
    limits = dict(initial_limits)
    for (day, code), limit in limits.items():
        _day(day)
        _text(code, "execution code")
        if not isinstance(limit, dependencies["event_limits"].EventLimits):
            raise EconomicBindingError("execution limits must be source-bound EventLimits")
    bound_keys: set[EventKey] = set()

    def bind(identity: EventIdentity, limit: Any = None) -> None:
        day, code, _identifier = identity
        key = (day, code)
        if key in bound_keys:
            raise EconomicBindingError(f"duplicate or colliding economic binding: {identity}")
        if identity not in unsupported:
            raise EconomicBindingError(f"bound identity is not unsupported: {identity}")
        if limit is not None:
            if key in limits:
                raise EconomicBindingError(f"execution limits collision: {key}")
            if not isinstance(limit, dependencies["event_limits"].EventLimits) or limit.source_id != identity[2]:
                raise EconomicBindingError("event limits must match the exact bound factor identity")
            limits[key] = limit
        bound_keys.add(key)
        unsupported.remove(identity)

    for capital_item in bindings.capital:
        bind(_identity(capital_item.event.resumed_on, capital_item.event.code, capital_item.factor_id))
    for share_item in (*bindings.shares, *bindings.mixed):
        bind(_identity(share_item.event.effective_on, share_item.event.code, share_item.factor_id), share_item.event.limits)
    for mixed_item in bindings.mixed:
        event = mixed_item.event
        entitlement = datetime.combine(event.effective_on, time(7), TAIPEI)
        matching = [term for term in terms if term.code == event.code and term.entitlement_at.date() == event.effective_on]
        if len(matching) != 1:
            raise EconomicBindingError("mixed distribution requires exactly one independent cash term")
        term = matching[0]
        if (
            term.event_id != f"cash:TWSE:{event.code}:{event.effective_on.isoformat()}"
            or term.credited_per_share != event.cash_per_share
            or term.entitlement_at != entitlement
            or term.payment_at != entitlement + timedelta(days=payment_delay_days)
            or term.source_available_at != entitlement
            or term.time_basis != "assumed"
        ):
            raise EconomicBindingError("mixed distribution cash term identity, amount or timing mismatch")
    for paid_item in bindings.paid:
        if not callable(paid_item.composer):
            raise EconomicBindingError("paid binding requires an explicit composer")
        bind(_identity(_at(paid_item.event.at).date(), paid_item.event.code, paid_item.event.event_id), paid_item.limits)
    remaining = tuple(sorted(unsupported))
    LOGGER.info("Bound economics: supported=%d unsupported=%d execution_limits=%d", len(bound_keys), len(remaining), len(limits))

    def build(diagnostics: list[dict[str, Any]], decisions: list[dict[str, Any]]) -> Callable[[], CorporateProvider]:
        def fresh() -> CorporateProvider:
            cash = dependencies["cash_terms"]
            coverage = cash.cash.CashCoverage(beginning, ending, True, "modeled-supplied-cash-domain-v1")
            provider = cash.build_cash_domain_provider(package, coverage=(coverage,))
            for capital_item in bindings.capital:
                provider = dependencies["capital_event"].build_capital_composer(provider, capital_item.event, beginning, ending)
            for share_item in bindings.shares:
                provider = dependencies["stock_rights"].build_share_composer(provider, share_item.event, beginning, ending)
            for mixed_item in bindings.mixed:
                provider = dependencies["mixed_rights"].build_mixed_share_composer(provider, mixed_item.event, beginning, ending)
            for paid_item in bindings.paid:
                provider = paid_item.composer(provider, paid_item.event, decisions)
            unsupported_at = tuple((datetime.combine(day, time(7), TAIPEI), code, identity) for day, code, identity in remaining)
            return corporate.guarded_cash_provider(provider, unsupported_at, diagnostics)

        return fresh

    return EconomicPlan(MappingProxyType(limits), frozenset(boundaries), remaining, build)

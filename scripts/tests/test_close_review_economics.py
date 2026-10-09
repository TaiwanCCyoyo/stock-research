"""Synthetic source-bound economics orchestration, with the native held guard."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_core.chronology import CorporateEvidence
from research_core.execution_prices import PriceLimits

ROOT = Path(__file__).resolve().parents[2]
LEAVES = ROOT / "tasks" / "20260921-evening-pilot"


def load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


economics = load("close_review_economics_under_test", ROOT / "tasks" / "20261005-relative-strength-holding" / "economics.py")
corporate = load("close_review_native_corporate", LEAVES / "corporate.py")
event_limits = load("close_review_native_event_limits", LEAVES / "event_limits.py")
TAIPEI = timezone(timedelta(hours=8))
DAY = date(2026, 1, 10)
BEGIN = datetime(2026, 1, 1, tzinfo=TAIPEI)
END = datetime(2026, 5, 1, tzinfo=TAIPEI)


def stamp(day: date, clock: time = time(7)) -> datetime:
    return datetime.combine(day, clock, TAIPEI)


def limit(identity: str) -> Any:
    return event_limits.EventLimits(PriceLimits(Decimal("10"), Decimal("20")), identity)


@dataclass(frozen=True)
class CashTerm:
    code: str = "M"
    event_id: str = f"cash:TWSE:M:{DAY}"
    credited_per_share: Decimal = Decimal("2")
    entitlement_at: datetime = stamp(DAY)
    payment_at: datetime = stamp(DAY) + timedelta(days=45)
    source_available_at: datetime = stamp(DAY)
    time_basis: str = "assumed"


def package(*, terms: tuple[Any, ...] = (), rights: tuple[Any, ...] = ()) -> Any:
    return SimpleNamespace(terms=terms, noncash_keys=rights)


def event(code: str, identity: str, day: date = DAY) -> Any:
    return SimpleNamespace(code=code, effective_on=day, resumed_on=day, at=stamp(day), event_id=identity, limits=limit(identity), cash_per_share=Decimal("2"))


@pytest.fixture
def modules() -> dict[str, Any]:
    calls: list[Any] = []
    providers: list[Any] = []
    notice = {"action": "SPLIT", "code": "A", "date": stamp(DAY).isoformat(), "time_basis": "assumed"}
    backdated = {"action": "SPLIT", "code": "B", "date": stamp(DAY - timedelta(days=1)).isoformat(), "time_basis": "date_only"}
    evidence = CorporateEvidence("injected-cash", (), True, (notice,), (backdated,))

    def cash_provider(supplied: Any, *, coverage: tuple[Any, ...]) -> Any:
        calls.append(("cash", supplied, coverage))

        def provide(since: datetime, until: datetime, prefix: Any) -> CorporateEvidence:
            return evidence

        providers.append(provide)
        return provide

    def composer(label: str) -> Any:
        def compose(base: Any, bound: Any, beginning: datetime, ending: datetime) -> Any:
            calls.append((label, bound, beginning, ending))

            def provide(since: datetime, until: datetime, prefix: Any) -> CorporateEvidence:
                return base(since, until, prefix)

            providers.append(provide)
            return provide

        return compose

    return {
        "cash_terms": SimpleNamespace(
            cash=SimpleNamespace(CashCoverage=lambda *args: args),
            build_cash_domain_provider=cash_provider,
        ),
        "corporate": corporate,
        "capital_event": SimpleNamespace(build_capital_composer=composer("capital")),
        "stock_rights": SimpleNamespace(build_share_composer=composer("shares")),
        "mixed_rights": SimpleNamespace(build_mixed_share_composer=composer("mixed")),
        "event_limits": event_limits,
        "calls": calls,
        "providers": providers,
        "evidence": evidence,
    }


def prepare(modules: Any, bindings: Any = None, **kwargs: Any) -> Any:
    return economics.prepare_economics(
        modules,
        bindings or economics.EconomicBindings(package()),
        factors=kwargs.pop("factors", ()),
        beginning=kwargs.pop("beginning", BEGIN),
        ending=kwargs.pop("ending", END),
        initial_limits=kwargs.pop("initial_limits", {}),
        **kwargs,
    )


def test_exact_domain_removal_fresh_composition_and_metadata(modules: Any) -> None:
    cap, share, mixed, paid = (event(code, code + ":factor") for code in ("C", "S", "M", "P"))
    decisions_seen: list[Any] = []

    def paid_composer(base: Any, offer: Any, decisions: Any) -> Any:
        modules["calls"].append(("paid", offer))
        decisions_seen.append(decisions)
        return base

    bindings = economics.EconomicBindings(
        package(terms=(CashTerm(),), rights=(("TWSE", "M", DAY.isoformat()),)),
        capital=(economics.BoundCapital(cap, cap.event_id),),
        shares=(economics.BoundShare(share, share.event_id),),
        mixed=(economics.BoundShare(mixed, mixed.event_id),),
        paid=(economics.BoundPaid(paid, paid_composer, paid.limits),),
    )
    factors = tuple((DAY, item.code, item.event_id) for item in (cap, share, mixed, paid)) + ((DAY, "U", "unbound"),)
    plan = prepare(modules, bindings, factors=factors)
    assert plan.unsupported == ((DAY, "U", "unbound"),)
    assert plan.corporate_keys == frozenset((DAY, code) for code in ("C", "S", "M", "P", "U"))
    assert set(plan.event_limits) == {(DAY, "S"), (DAY, "M"), (DAY, "P")}
    assert (DAY, "C") not in plan.event_limits  # A refund cannot fabricate limits.
    diagnostics: list[Any] = []
    decisions: list[Any] = []
    factory = plan.new_factory(diagnostics, decisions)
    first, second = factory(), factory()
    assert first is not second
    assert len({id(provider) for provider in modules["providers"]}) == 8
    assert [item[0] for item in modules["calls"]] == ["cash", "capital", "shares", "mixed", "paid"] * 2
    assert modules["calls"][0][2] == ((BEGIN, END, True, "modeled-supplied-cash-domain-v1"),)
    assert decisions_seen == [decisions, decisions]
    evidence = first(BEGIN, END, ())
    assert evidence is modules["evidence"]
    assert evidence.share_count_notices[0]["time_basis"] == "assumed"
    assert evidence.backdated[0]["time_basis"] == "date_only"
    with pytest.raises(TypeError):
        plan.event_limits[(DAY, "X")] = limit("X")


def test_limits_only_never_remove_unsupported_and_native_guard_checks_held(modules: Any) -> None:
    identity = "named:9945:LIMITS-ONLY"
    supplied_limits = {(DAY, "9945"): limit(identity)}
    plan = prepare(modules, factors=((DAY, "9945", identity),), initial_limits=supplied_limits)
    assert plan.unsupported == ((DAY, "9945", identity),)
    supplied_limits.clear()
    assert (DAY, "9945") in plan.event_limits
    diagnostics: list[Any] = []
    provider = plan.new_factory(diagnostics, [])()
    assert provider(BEGIN, END, ()).complete
    prefix = ({"action": "BUY", "code": "9945", "qty": 1000, "total": -10_000, "date": (BEGIN + timedelta(days=1)).isoformat()},)
    result = provider(BEGIN + timedelta(days=2), END, prefix)
    assert result.complete is False and result.events == ()
    assert diagnostics == [{"reason": "held_noncash_event_not_bound", "at": stamp(DAY).isoformat(), "code": "9945", "event_id": identity}]


def test_cash_and_rights_union_without_factor_does_not_disappear(modules: Any) -> None:
    plan = prepare(modules, economics.EconomicBindings(package(terms=(CashTerm(),), rights=(("TWSE", "R", DAY.isoformat()),))))
    assert plan.corporate_keys == frozenset({(DAY, "M"), (DAY, "R")})
    assert plan.unsupported == ((DAY, "R", f"rights:R:{DAY}"),)


@pytest.mark.parametrize("problem", ["wrong_identity", "duplicate_binding", "cross_domain", "limits_collision", "wrong_limits_identity"])
def test_binding_duplicates_and_collisions_rejected(modules: Any, problem: str) -> None:
    share = event("S", "S:factor")
    shares: tuple[Any, ...] = (economics.BoundShare(share, "wrong" if problem == "wrong_identity" else share.event_id),)
    capital: tuple[Any, ...] = ()
    initial = {}
    if problem == "duplicate_binding":
        shares *= 2
    elif problem == "cross_domain":
        capital = (economics.BoundCapital(share, share.event_id),)
    elif problem == "limits_collision":
        initial = {(DAY, "S"): share.limits}
    elif problem == "wrong_limits_identity":
        share.limits = limit("wrong")
    with pytest.raises(economics.EconomicBindingError):
        prepare(modules, economics.EconomicBindings(package(), capital=capital, shares=shares), factors=((DAY, "S", "S:factor"),), initial_limits=initial)


@pytest.mark.parametrize("factors", [((DAY, "S", "same"),) * 2, ((DAY, "S", "one"), (DAY, "S", "two"))])
def test_duplicate_factor_keys_rejected(modules: Any, factors: Any) -> None:
    with pytest.raises(economics.EconomicBindingError, match="factor identities"):
        prepare(modules, factors=factors)


@pytest.mark.parametrize("problem", ["absent", "duplicate", "amount", "identity", "entitlement", "payment", "availability", "basis"])
def test_mixed_requires_exact_independent_cash_term(modules: Any, problem: str) -> None:
    term = CashTerm()
    if problem == "amount":
        term = replace(term, credited_per_share=Decimal("2.01"))
    elif problem == "identity":
        term = replace(term, event_id="cash:TPEX:M:2026-01-10")
    elif problem == "entitlement":
        term = replace(term, entitlement_at=stamp(DAY, time(7, 1)))
    elif problem == "payment":
        term = replace(term, payment_at=stamp(DAY) + timedelta(days=90))
    elif problem == "availability":
        term = replace(term, source_available_at=stamp(DAY, time(8)))
    elif problem == "basis":
        term = replace(term, time_basis="exact")
    terms = () if problem == "absent" else (term,) * (2 if problem == "duplicate" else 1)
    mixed = event("M", "M:factor")
    bindings = economics.EconomicBindings(package(terms=terms, rights=(("TWSE", "M", DAY.isoformat()),)), mixed=(economics.BoundShare(mixed, mixed.event_id),))
    with pytest.raises(economics.EconomicBindingError):
        prepare(modules, bindings, factors=((DAY, "M", mixed.event_id),))


def test_ninety_day_cash_model_is_explicit_and_never_adds_terms(modules: Any) -> None:
    term = replace(CashTerm(), payment_at=stamp(DAY) + timedelta(days=90))
    supplied = package(terms=(term,), rights=(("TWSE", "M", DAY.isoformat()),))
    mixed = event("M", "M:factor")
    bindings = economics.EconomicBindings(supplied, mixed=(economics.BoundShare(mixed, mixed.event_id),))
    plan = prepare(modules, bindings, factors=((DAY, "M", mixed.event_id),), payment_delay_days=90)
    plan.new_factory([], [])()
    assert modules["calls"][0][1] is supplied and supplied.terms == (term,)


@pytest.mark.parametrize(
    "changes", [{"beginning": END}, {"ending": BEGIN}, {"beginning": BEGIN.replace(tzinfo=None)}, {"payment_delay_days": 0}, {"payment_delay_days": True}]
)
def test_invalid_coverage_or_timing_fails_before_factory(modules: Any, changes: Any) -> None:
    with pytest.raises(economics.EconomicBindingError):
        prepare(modules, **changes)
    assert modules["calls"] == []


def test_distinct_scenario_sinks_forwarded_to_fresh_factories(modules: Any) -> None:
    plan = prepare(modules, factors=((DAY, "U", "unbound"),))
    first_diagnostics: list[Any] = []
    second_diagnostics: list[Any] = []
    first = plan.new_factory(first_diagnostics, [])()
    second = plan.new_factory(second_diagnostics, [])()
    prefix = ({"action": "BUY", "code": "U", "qty": 1000, "total": -10_000, "date": (BEGIN + timedelta(days=1)).isoformat()},)
    assert not first(BEGIN + timedelta(days=2), END, prefix).complete
    assert second(BEGIN + timedelta(days=2), END, ()).complete
    assert first_diagnostics and second_diagnostics == []

"""Synthetic orders against retained execution leaves; no market/account run."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_core.auction import AccountState, AuctionBatch, CostSchedule, OrderIntent, RoutedOrder
from research_core.chronology import ExecutionWindow, SessionRoute
from research_core.decision import ExecutionAccountSnapshot
from research_core.execution_prices import PriceLimits
from research_core.order_lifecycle import reconcile_cohort_lifecycle

ROOT = Path(__file__).resolve().parents[2]
TASK = ROOT / "tasks/20261005-relative-strength-holding"
TAIPEI = timezone(timedelta(hours=8))
PRIOR, HALT, RESUME = date(2021, 10, 20), date(2021, 10, 21), date(2021, 10, 22)
CALENDAR = (PRIOR, HALT, RESUME)
COSTS = CostSchedule(Fraction(0), 0, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")


def load(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, TASK / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


execution = load("close_review_execution_under_test", "execution.py")


@pytest.fixture(scope="module")
def modules() -> dict[str, Any]:
    return load("close_review_execution_sources", "source_modules.py").load_execution_adapters()


def stamp(day: date, clock: time) -> datetime:
    return datetime.combine(day, clock, TAIPEI)


def raw() -> dict[Any, dict[str, Any]]:
    return {
        (PRIOR, "A"): {"Close": 100.0, "source_id": "synthetic:reference"},
        (HALT, "A"): {"Open": 101.0, "Close": 102.0, "Volume": 1000, "source_id": "synthetic:halt"},
        (RESUME, "A"): {"Open": 103.0, "Close": 104.0, "source_id": "synthetic:resumed"},
    }


def bound_factory(modules: Any, rows: Any, **overrides: Any) -> tuple[Any, list[Any], list[Any]]:
    diagnostics: list[Any] = []
    audit: list[Any] = []
    arguments = dict(
        raw_by_key=rows,
        calendar=CALENDAR,
        economics=SimpleNamespace(corporate_keys=frozenset(), event_limits={}),
        halt_cases=(),
        no_trade=None,
        confirmed_halts={},
        diagnostics=diagnostics,
        resumption_audit=audit,
    )
    arguments.update(overrides)
    return execution.build_execution_factory(modules, **arguments), diagnostics, audit


def route(
    day: date = HALT, *, code: str = "A", side: str = "BUY", price: int = 11000, venue: str = "regular_open", qty: int = 1000, exchange: str = "TWSE"
) -> RoutedOrder:
    submitted, auction = (time(14), time(14, 30)) if venue == "afterhours_odd" else (time(8, 55), time(9))
    return RoutedOrder(
        OrderIntent(f"synthetic:{day}:{code}:{side}", code, side, qty, price, stamp(PRIOR, time(20))),
        AuctionBatch(exchange, venue, stamp(day, submitted), stamp(day, auction), f"synthetic:{day}:{exchange}:{venue}"),
        COSTS,
    )


def observe(provider: Any, order: RoutedOrder) -> tuple[Any, Any]:
    window = ExecutionWindow(
        "synthetic-window", (SessionRoute(order.batch, COSTS),), stamp(order.batch.auction_at.date(), time(15)), stamp(order.batch.auction_at.date(), time(15))
    )
    positions = {order.order.code: order.order.qty} if order.order.side == "SELL" else {}
    snapshot = ExecutionAccountSnapshot(
        AccountState(200_000_000, positions, order.batch.submitted_at, "trade_date_cash"), 0, 0, "synthetic-calendar", "synthetic-checkpoint", "synthetic"
    )
    evidence = provider(window, snapshot, (order,))
    reconciled = None
    if evidence.complete:
        reconciled = reconcile_cohort_lifecycle(
            snapshot.account, (order,), evidence.quotes, max_positions=5, expires_at=window.expires_at, as_of=window.as_of, reports=evidence.reports
        )
    return evidence, reconciled


def test_regular_open_uses_previous_calendar_close_and_freezes_rows(modules: Any) -> None:
    rows = raw()
    factory, diagnostics, _audit = bound_factory(modules, rows)
    rows[(PRIOR, "A")]["Close"] = 1.0
    rows[(HALT, "A")]["Open"] = 1.0
    rows.clear()
    first, second = factory(), factory()
    assert first is not second
    for provider in (first, second):
        evidence, result = observe(provider, route())
        quote = next(iter(evidence.quotes.values()))
        assert evidence.complete and quote.price_cents == 10100
        assert quote.limits == PriceLimits(Decimal(90), Decimal(110))
        assert result.initial_result.outcomes[0].filled_qty == 1000
    assert not diagnostics


@pytest.mark.parametrize("value", [None, float("nan"), 0, 100.03])
def test_missing_or_invalid_open_is_incomplete_without_fill(modules: Any, value: Any) -> None:
    rows = raw()
    rows[(HALT, "A")]["Open"] = value
    factory, diagnostics, _audit = bound_factory(modules, rows)
    evidence, result = observe(factory(), route())
    assert not evidence.complete and not evidence.quotes and not evidence.reports and result is None
    assert diagnostics[0]["reason"] == "missing_nonfinite_nonpositive_or_offgrid_open"


@pytest.mark.parametrize(("side", "open_price", "limit"), [("BUY", 110.0, 11000), ("SELL", 90.0, 9000)])
def test_adverse_locked_limit_does_not_guarantee_fill(modules: Any, side: str, open_price: float, limit: int) -> None:
    rows = raw()
    rows[(HALT, "A")]["Open"] = open_price
    factory, _diagnostics, _audit = bound_factory(modules, rows)
    evidence, result = observe(factory(), route(side=side, price=limit))
    assert evidence.complete and next(iter(evidence.quotes.values())).allocated_shares == 0
    assert result.initial_result.outcomes[0].filled_qty == 0
    assert evidence.reports[0].status == "EXPIRED"


def case(modules: Any, resumed: date = RESUME) -> Any:
    return modules["resumption_execution"].ResumptionCase(
        "A", PRIOR, HALT, resumed, 10000, "synthetic:named-halt", "synthetic:reference", "synthetic:resumed", "synthetic:halt"
    )


def test_named_halt_expires_and_resumption_uses_named_reference(modules: Any) -> None:
    rows = raw()
    rows[(HALT, "A")].update(Open=None, Close=float("nan"), Volume=0)
    factory, diagnostics, audit = bound_factory(modules, rows, halt_cases=(case(modules),), confirmed_halts={(HALT, "A"): "synthetic:named-halt"})
    evidence, result = observe(factory(), route())
    assert evidence.complete and next(iter(evidence.quotes.values())).status == "HALT"
    assert result.initial_result.outcomes[0].filled_qty == 0 and evidence.reports[0].status == "EXPIRED"
    resumed, result = observe(factory(), route(RESUME))
    quote = next(iter(resumed.quotes.values()))
    assert resumed.complete and quote.price_cents == 10300
    assert quote.limits == PriceLimits(Decimal(90), Decimal(110))
    assert "named-resumed-reference" in quote.source_id
    assert result.initial_result.outcomes[0].filled_qty == 1000
    assert audit[0]["reference_day"] == PRIOR.isoformat() and not diagnostics


def test_unknown_gap_is_not_treated_as_named_resumption(modules: Any) -> None:
    rows = raw()
    rows[(HALT, "A")]["Close"] = None
    factory, diagnostics, _audit = bound_factory(modules, rows)
    evidence, result = observe(factory(), route(RESUME))
    assert not evidence.complete and result is None
    assert diagnostics[0]["reason"] == "missing_strictly_previous_session_finite_positive_close"


def test_afterhours_odd_uses_modeled_close_proxy(modules: Any) -> None:
    rows = raw()
    rows[(HALT, "A")]["Open"] = 105.0
    factory, _diagnostics, _audit = bound_factory(modules, rows)
    evidence, result = observe(factory(), route(side="SELL", price=9000, venue="afterhours_odd", qty=501))
    quote = next(iter(evidence.quotes.values()))
    assert quote.price_cents == 10200 and "modeled:afterhours-regular-close-proxy-v1" in quote.source_id
    assert result.initial_result.outcomes[0].filled_qty == 501


def test_unknown_economic_event_is_not_removed_from_execution_domain(modules: Any) -> None:
    plan = SimpleNamespace(corporate_keys=frozenset({(HALT, "A")}), event_limits={})
    factory, diagnostics, _audit = bound_factory(modules, raw(), economics=plan)
    evidence, _result = observe(factory(), route())
    assert not evidence.complete
    assert diagnostics[0]["reason"] == "corporate_event_requires_verified_cash_event_limits"
    plan.event_limits[(HALT, "A")] = modules["event_limits"].EventLimits(PriceLimits(Decimal(90), Decimal(110)), "synthetic:event")
    factory, diagnostics, _audit = bound_factory(modules, raw(), economics=plan)
    plan.event_limits.clear()
    evidence, result = observe(factory(), route())
    assert evidence.complete and result.initial_result.outcomes[0].filled_qty == 1000 and not diagnostics


def test_single_source_bound_no_trade_is_regular_only_and_does_not_cover_other_issuers(modules: Any) -> None:
    payload = {
        "market": "TPEx",
        "code": "4192",
        "date": HALT.isoformat(),
        "source_dataset_sha": "synthetic-sha",
        "open": None,
        "close": None,
        "volume": 0,
        "raw_fields": {
            "代號": "4192",
            **dict.fromkeys(("開盤", "收盤", "最高", "最低"), "----"),
            **dict.fromkeys(("成交股數", "成交筆數", "成交金額(元)"), "0"),
        },
    }
    bound = modules["no_trade_execution"].bind_no_trade_source(payload, "synthetic-sha")
    rows = raw()
    rows[(HALT, "4192")] = {"Open": None, "Close": None, "Volume": 0, "source_id": "tpex-official:synthetic-sha|synthetic"}
    factory, _diagnostics, _audit = bound_factory(modules, rows, no_trade=bound)
    evidence, result = observe(factory(), route(code="4192", exchange="TPEX"))
    assert evidence.complete and next(iter(evidence.quotes.values())).status == "NO_TRADE"
    assert result.initial_result.outcomes[0].filled_qty == 0 and evidence.reports[0].status == "EXPIRED"
    odd, _result = observe(factory(), route(code="4192", exchange="TPEX", side="SELL", venue="afterhours_odd", qty=501))
    assert not odd.complete
    other, _result = observe(factory(), route(code="unknown", exchange="TPEX"))
    assert not other.complete


@pytest.mark.parametrize("calendar", [(), (HALT, PRIOR), (PRIOR, PRIOR), [PRIOR, HALT], (datetime(2021, 10, 20), HALT)])
def test_calendar_must_be_strict_date_tuple(modules: Any, calendar: Any) -> None:
    with pytest.raises(execution.ExecutionBindingError, match="calendar"):
        bound_factory(modules, {}, calendar=calendar)


def test_raw_keys_outside_calendar_and_partial_named_case_fail(modules: Any) -> None:
    with pytest.raises(execution.ExecutionBindingError, match="outside calendar"):
        bound_factory(modules, raw(), calendar=(HALT, RESUME))
    rows = {key: row for key, row in raw().items() if key[0] != PRIOR}
    with pytest.raises(execution.ExecutionBindingError, match="reference and halt"):
        bound_factory(modules, rows, calendar=(HALT, RESUME), halt_cases=(case(modules),))
    # A future named resumption is entirely outside this run and is not patched.
    factory, _diagnostics, audit = bound_factory(modules, raw(), halt_cases=(case(modules, RESUME + timedelta(days=1)),))
    evidence, _result = observe(factory(), route())
    assert evidence.complete and not audit

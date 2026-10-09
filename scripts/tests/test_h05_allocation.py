"""Synthetic retained native/resumption quotes and real shared lifecycle."""

from datetime import time
from typing import Any

import pytest

from scripts.tests import test_close_review_execution as native_tests

allocation = native_tests.load("h05_allocation_under_test", "allocation.py")


@pytest.fixture(scope="module")
def modules() -> dict[str, Any]:
    return native_tests.load("h05_allocation_sources", "source_modules.py").load_execution_adapters()


def wrapper(modules: Any, **overrides: Any) -> tuple[Any, list[Any]]:
    rows = overrides.pop("rows", native_tests.raw())
    factory, _diagnostics, _resumption_audit = native_tests.bound_factory(modules, rows, **overrides)
    audit: list[Any] = []
    return allocation.half_allocation_factory(
        factory,
        native_module=modules["no_trade_execution"],
        modeled_module=modules["modeled_execution"],
        audit=audit,
    ), audit


@pytest.mark.parametrize(
    "venue,qty,filled", [("regular_open", 5000, 2000), ("regular_open", 1000, 1000), ("afterhours_odd", 501, 250), ("afterhours_odd", 1, 1)]
)
def test_partial_and_final_unit_exits_reconcile(modules: Any, venue: str, qty: int, filled: int) -> None:
    factory, audit = wrapper(modules)
    order = native_tests.route(side="SELL", venue=venue, qty=qty, price=9000)
    evidence, result = native_tests.observe(factory(), order)
    assert evidence.complete and result is not None
    assert result.initial_result.outcomes[0].filled_qty == filled
    assert not result.unresolved_order_ids
    quote = next(iter(evidence.quotes.values()))
    assert quote.price_cents == (10200 if venue == "afterhours_odd" else 10100)
    assert allocation.BASIS in quote.capacity_basis
    assert audit[0]["requested_qty"] == qty
    assert audit[0]["native_allocation"] == qty
    if filled < qty:
        assert len(evidence.reports) == 1
        assert evidence.reports[0].status == "CANCELLED"
        assert evidence.reports[0].cumulative_filled_qty == filled
        assert allocation.MODEL_ID in evidence.reports[0].source_id
    else:
        assert not evidence.reports
        assert result.initial_result.next_state is not None
        assert not result.initial_result.next_state.positions


def test_native_zero_allocation_is_not_raised(modules: Any) -> None:
    rows = native_tests.raw()
    rows[(native_tests.HALT, "A")]["Open"] = 110.0
    factory, audit = wrapper(modules, rows=rows)
    evidence, result = native_tests.observe(factory(), native_tests.route(qty=5000))
    assert next(iter(evidence.quotes.values())).allocated_shares == 0
    assert result.initial_result.outcomes[0].filled_qty == 0
    assert evidence.reports[0].status == "EXPIRED"
    assert evidence.reports[0].cumulative_filled_qty == 0
    assert audit[0]["modeled_allocation"] == 0


def test_unknown_remains_incomplete(modules: Any) -> None:
    rows = native_tests.raw()
    rows[(native_tests.HALT, "A")]["Open"] = None
    factory, audit = wrapper(modules, rows=rows)
    evidence, result = native_tests.observe(factory(), native_tests.route(qty=5000))
    assert not evidence.complete and not evidence.quotes and not evidence.reports
    assert result is None and not audit


def test_verified_no_trade_preserves_status_and_no_fill(modules: Any) -> None:
    day = native_tests.HALT
    payload = {
        "market": "TPEx",
        "code": "4192",
        "date": day.isoformat(),
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
    no_trade = modules["no_trade_execution"].bind_no_trade_source(payload, "synthetic-sha")
    rows = native_tests.raw()
    rows[(day, "4192")] = {"Open": None, "Close": None, "Volume": 0, "source_id": "tpex-official:synthetic-sha|synthetic"}
    factory, audit = wrapper(modules, rows=rows, no_trade=no_trade)
    evidence, result = native_tests.observe(factory(), native_tests.route(code="4192", exchange="TPEX", qty=5000))
    assert evidence.complete and next(iter(evidence.quotes.values())).status == "NO_TRADE"
    assert result.initial_result.outcomes[0].filled_qty == 0
    assert evidence.reports[0].status == "EXPIRED" and not audit


def test_named_halt_and_resumption_survive_half_allocation(modules: Any) -> None:
    rows = native_tests.raw()
    rows[(native_tests.HALT, "A")].update(Open=None, Close=None, Volume=0)
    factory, audit = wrapper(
        modules,
        rows=rows,
        halt_cases=(native_tests.case(modules),),
        confirmed_halts={(native_tests.HALT, "A"): "synthetic:named-halt"},
    )
    halted, _result = native_tests.observe(factory(), native_tests.route(qty=5000))
    assert halted.complete and next(iter(halted.quotes.values())).status == "HALT"
    assert halted.reports[0].status == "EXPIRED" and not audit
    evidence, result = native_tests.observe(factory(), native_tests.route(native_tests.RESUME, qty=5000))
    quote = next(iter(evidence.quotes.values()))
    assert quote.price_cents == 10300 and "named-resumed-reference" in quote.source_id
    assert result.initial_result.outcomes[0].filled_qty == 2000
    assert evidence.reports[0].cumulative_filled_qty == 2000
    assert not result.unresolved_order_ids


def test_independent_factories_and_bad_native_shape(modules: Any) -> None:
    factory, _audit = wrapper(modules)
    assert factory() is not factory()
    bad = allocation.half_allocation_factory(
        lambda: lambda *args: None,
        native_module=modules["no_trade_execution"],
        modeled_module=modules["modeled_execution"],
        audit=[],
    )
    with pytest.raises(ValueError, match="verified native provider closure"):
        bad()


def test_unsupported_venue_and_empty_routes_fail(modules: Any) -> None:
    from research_core.auction import AuctionBatch, RoutedOrder

    factory, _audit = wrapper(modules)
    order = native_tests.route(venue="afterhours_odd", qty=1)
    odd = AuctionBatch(
        "TWSE", "intraday_odd", native_tests.stamp(native_tests.HALT, time(9)), native_tests.stamp(native_tests.HALT, time(9, 10)), "unsupported"
    )
    with pytest.raises(ValueError, match="supports regular_open"):
        native_tests.observe(factory(), RoutedOrder(order.order, odd, order.costs))
    provider = factory()
    with pytest.raises(ValueError, match="nonempty"):
        provider(None, None, ())

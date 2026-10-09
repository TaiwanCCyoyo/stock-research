from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any, cast

import pytest

from research_core.auction import AccountState, AuctionBatch, AuctionQuote, CostSchedule, OrderIntent
from research_core.execution_prices import PriceLimits
from research_core.order_lifecycle import FillReport, LifecycleError, LifecycleResult, TerminalReport, reconcile_order_lifecycle

TZ = "+08:00"


def t(clock: str, day: int = 5) -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{clock}:00{TZ}")


LIMITS = PriceLimits(Decimal("90"), Decimal("110"))


def costs() -> CostSchedule:
    return CostSchedule(Fraction(0), 2_000, 1, "ceil", Fraction(3, 1000), 1, "ceil", Fraction(0), 1, "ceil")


def setup(side: str = "BUY", capacity: int = 1000) -> tuple[AccountState, list[OrderIntent], dict[str, AuctionQuote], AuctionBatch]:
    order = OrderIntent("o", "A", side, 1000, 10000, t("16:00", 4))
    state = AccountState(20_000_000, {} if side == "BUY" else {"A": 1000}, t("07:00", 4), "trade_date_cash")
    batch = AuctionBatch("TWSE", "regular_open", t("08:55"), t("09:00"), "s")
    return state, [order], {"A": AuctionQuote("TRADED", 10000, LIMITS, capacity, "q", "cap")}, batch


def fill(qty: int = 1000, at: str = "10:00", price: int = 10000, rid: str = "f", seq: int = 1) -> FillReport:
    return FillReport(rid, "o", t(at), t(at), seq, qty, price, LIMITS, "r", "later")


def terminal(status: str = "FILLED", qty: int = 1000, at: str = "10:01", rid: str = "x", seq: int = 2) -> TerminalReport:
    return TerminalReport(rid, "o", t(at), t(at), seq, status, qty, "r")


def call(reports: Sequence[FillReport | TerminalReport], **kw: Any) -> LifecycleResult:
    state, orders, quotes, batch = setup(**kw.pop("setup", {}))
    return reconcile_order_lifecycle(
        state, orders, quotes, batch=batch, costs=costs(), max_positions=2, expires_at=t("13:30"), as_of=t("13:30"), reports=reports
    )


def test_initial_zero_later_fill_uses_one_cumulative_minimum_commission() -> None:
    result = call([fill(1000), terminal()], setup={"capacity": 0})
    assert result.continuation_allowed and result.additional_events[0]["commission_cents"] == 2000
    assert result.next_state and result.next_state.positions["A"] == 1000


def test_future_report_is_not_known_and_blocks_continuation() -> None:
    state, orders, quotes, batch = setup(capacity=0)
    report = FillReport("f", "o", t("10:00"), t("14:00"), 1, 1000, 10000, LIMITS, "r", "later")
    result = reconcile_order_lifecycle(
        state, orders, quotes, batch=batch, costs=costs(), max_positions=2, expires_at=t("13:30"), as_of=t("13:30"), reports=[report]
    )
    assert result.next_state is None and result.unresolved_order_ids == ("o",)


@pytest.mark.parametrize("reports", [[fill(qty=500)], [terminal("CANCELLED", 1)], [fill(rid="a", seq=2), fill(rid="a", seq=3)]])
def test_invalid_report_contracts_fail(reports: Sequence[FillReport | TerminalReport]) -> None:
    with pytest.raises(LifecycleError):
        call(reports, setup={"capacity": 0})


def test_afterhours_rejects_later_fill() -> None:
    state, orders, quotes, _ = setup(capacity=0)
    batch = AuctionBatch("TWSE", "afterhours_odd", t("14:00"), t("14:30"), "s")
    orders = [OrderIntent("o", "A", "BUY", 10, 10000, t("16:00", 4))]
    with pytest.raises(LifecycleError):
        reconcile_order_lifecycle(
            state,
            orders,
            quotes,
            batch=batch,
            costs=costs(),
            max_positions=2,
            expires_at=t("15:00"),
            as_of=t("15:00"),
            reports=[FillReport("f", "o", t("14:40"), t("14:40"), 1, 10, 10000, LIMITS, "r", "later")],
        )


def test_unknown_initial_batch_cannot_be_rescued_by_a_terminal_report() -> None:
    state = AccountState(50_000_000, {}, t("16:00", 4), "trade_date_cash")
    orders = [
        OrderIntent("a", "A", "BUY", 1_000, 10_000, t("16:00", 4)),
        OrderIntent("b", "B", "BUY", 1_000, 10_000, t("16:00", 4)),
    ]
    batch = AuctionBatch("TWSE", "regular_open", t("08:55"), t("09:00"), "s")
    result = reconcile_order_lifecycle(
        state,
        orders,
        {"A": AuctionQuote("TRADED", 10_000, LIMITS, 1_000, "auction", "cap")},
        batch=batch,
        costs=costs(),
        max_positions=2,
        expires_at=t("13:30"),
        as_of=t("13:30"),
        reports=[TerminalReport("b-filled", "b", t("13:30"), t("13:30"), 1, "FILLED", 1_000, "report")],
    )
    assert result.initial_result.state_complete is False
    assert result.next_state is None
    assert result.additional_events == ()


def run_case(
    reports: Sequence[FillReport | TerminalReport],
    *,
    requested: int = 2000,
    capacity: int = 1000,
    side: str = "BUY",
    venue: str = "regular_open",
    price: int = 10000,
    limit: int = 11000,
    limits: PriceLimits = LIMITS,
    cash: int = 50_000_000,
    cost_schedule: CostSchedule | None = None,
    cutoff: str = "13:30",
    halt: bool = False,
    cash_basis: str = "trade_date_cash",
) -> LifecycleResult:
    clocks = {"regular_open": "09:00", "intraday_odd": "09:10", "afterhours_odd": "14:30"}
    submissions = {"regular_open": "08:55", "intraday_odd": "09:05", "afterhours_odd": "14:00"}
    expiry = "14:30" if venue == "afterhours_odd" else "13:30"
    batch = AuctionBatch("TWSE", venue, t(submissions[venue]), t(clocks[venue]), "synthetic")
    state = AccountState(cash, {} if side == "BUY" else {"A": requested}, t("16:00", 4), cash_basis)
    quote = (
        AuctionQuote("HALT", None, None, None, "synthetic-halt")
        if halt
        else AuctionQuote("TRADED", price, limits, capacity, "synthetic-print", "synthetic-allocation")
    )
    return reconcile_order_lifecycle(
        state,
        [OrderIntent("o", "A", side, requested, limit, t("16:00", 4))],
        {"A": quote},
        batch=batch,
        costs=cost_schedule or costs(),
        max_positions=5,
        expires_at=t(expiry),
        as_of=t(cutoff),
        reports=reports,
    )


def test_minimum_not_recharged_on_later_partial_at_different_price() -> None:
    result = run_case([fill(price=10100), terminal(qty=2000)])
    assert result.continuation_allowed and result.next_state is not None
    assert result.initial_result.outcomes[0].commission_cents == 2000
    assert result.additional_events[0]["commission_cents"] == 0
    assert result.additional_events[0]["gross_cents"] == 10_100_000
    assert result.next_state.cash_cents == 29_898_000
    with pytest.raises(TypeError):
        cast(Any, result.additional_events[0])["total_cents"] = 0


def test_zero_initial_then_partial_cancel_charges_once_without_inventing_residual() -> None:
    result = run_case([fill(), terminal(status="CANCELLED")], capacity=0)
    assert result.continuation_allowed and result.next_state is not None
    assert result.next_state.positions == {"A": 1000}
    assert result.next_state.cash_cents == 39_998_000
    assert len(result.additional_events) == 1


def test_tiny_sale_debit_reservation_and_no_duplicate_minimum() -> None:
    tiny_limits = PriceLimits(Decimal("0.01"), None)
    schedule = CostSchedule(Fraction(0), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
    reports: list[FillReport | TerminalReport] = [
        FillReport("f", "o", t("10:00"), t("10:00"), 1, 99, 1, tiny_limits, "tiny-print", "fixed"),
        terminal(qty=100),
    ]
    result = run_case(
        reports, requested=100, capacity=1, side="SELL", venue="intraday_odd", price=1, limit=1, limits=tiny_limits, cash=1999, cost_schedule=schedule
    )
    assert result.continuation_allowed
    assert result.next_state is not None
    assert result.initial_result.outcomes[0].reserved_cash_cents == 1999
    assert result.initial_result.ledger_events[0]["total"] == -19.99
    assert result.additional_events[0]["total_cents"] == 99
    assert result.additional_events[0]["commission_cents"] == 0
    assert result.next_state.cash_cents == 99
    assert result.next_state.positions == {}
    rejected = run_case(
        [], requested=100, capacity=1, side="SELL", venue="intraday_odd", price=1, limit=1, limits=tiny_limits, cash=1998, cost_schedule=schedule
    )
    assert rejected.initial_result.outcomes[0].reason == "insufficient_reserved_cash"
    assert rejected.initial_result.ledger_events == ()


def test_fractional_cost_rounding_is_on_cumulative_notional() -> None:
    schedule = CostSchedule(Fraction(1, 3000), 2000, 100, "ceil", Fraction(1, 1000), 100, "ceil", Fraction(1, 7000), 100, "half_up")
    result = run_case([fill(price=10100), terminal(qty=2000)], side="SELL", limit=9000, cost_schedule=schedule)
    assert result.continuation_allowed and result.next_state is not None
    initial = result.initial_result.outcomes[0]
    assert (initial.commission_cents, initial.tax_cents, initial.penalty_cents) == (3400, 10000, 1400)
    later = result.additional_events[0]
    assert (later["commission_cents"], later["tax_cents"], later["penalty_cents"]) == (3300, 10100, 1500)
    assert later["cost_total"] == 149
    assert result.next_state.cash_cents == 70_070_300


def test_hidden_fill_before_visible_terminal_is_incomplete_not_known_zero() -> None:
    hidden = replace(fill(), available_at=t("14:00"))
    result = run_case([hidden, terminal()], requested=1000, capacity=0)
    assert not result.continuation_allowed
    assert result.additional_events == ()
    assert result.next_state is None
    assert result.unresolved_order_ids == ("o",)
    known = run_case([hidden, terminal()], requested=1000, capacity=0, cutoff="14:01")
    assert known.continuation_allowed and known.next_state is not None
    assert known.next_state.positions == {"A": 1000}


def test_full_initial_fill_changes_settled_label_even_without_later_reports() -> None:
    result = run_case([], requested=1000, cash_basis="settled_cash")
    assert result.continuation_allowed and result.next_state is not None
    assert result.next_state.cash_basis == "trade_date_cash"


def test_expiry_boundary_and_afterhours_terminal_are_explicit() -> None:
    filled = run_case([fill(at="13:30"), terminal(qty=2000, at="13:30")])
    assert filled.continuation_allowed
    expiry = terminal(status="EXPIRED", qty=0, at="14:30", seq=1)
    expired = run_case([expiry], venue="afterhours_odd", requested=10, capacity=0, cutoff="14:30")
    assert expired.continuation_allowed and expired.additional_events == ()
    no_report = run_case([], requested=1000, capacity=0, cutoff="16:00")
    assert not no_report.continuation_allowed
    assert no_report.next_state is None


@pytest.mark.parametrize(
    ("reports", "reason"),
    [
        ([terminal(status="CANCELLED", qty=1000, seq=1), fill(at="11:00", seq=2)], "fill follows terminal"),
        ([terminal(status="CANCELLED", qty=1000, rid="t1", seq=1), terminal(status="CANCELLED", qty=1000, rid="t2", seq=2)], "duplicate terminal"),
        ([fill(seq=2), terminal(qty=2000, seq=1)], "sequence"),
        ([fill(at="11:00"), terminal(qty=2000, at="10:00")], "nondecreasing"),
        ([fill(qty=2000)], "exceeds order"),
        ([terminal(qty=2000)], "does not match"),
        ([terminal(status="REJECTED", qty=0)], "does not match"),
        ([terminal(status="EXPIRED", qty=1000, at="13:29")], "exactly at expiry"),
        ([fill(at="13:31")], "before expiry"),
        ([fill(at="09:00")], "after auction"),
    ],
)
def test_explicit_lifecycle_contradictions_have_specific_errors(reports: Sequence[FillReport | TerminalReport], reason: str) -> None:
    with pytest.raises(LifecycleError, match=reason):
        run_case(reports, cutoff="16:00")  # Every tested contradiction is already observable.


def test_same_order_cannot_change_daily_bounds_after_initial_missing_bounds() -> None:
    second = replace(fill(rid="f2", at="11:00", seq=2), limits=PriceLimits(Decimal("91"), Decimal("110")))
    with pytest.raises(LifecycleError, match="daily price limits"):
        run_case([fill(), second], capacity=0, halt=True)


def test_valid_market_print_still_cannot_violate_buy_order_limit() -> None:
    with pytest.raises(LifecycleError, match="order limit"):
        run_case([fill(price=10050)], limit=10000)


def test_reports_for_initially_filled_or_rejected_orders_are_not_residuals() -> None:
    for amount in (50_000_000, 1):
        with pytest.raises(LifecycleError, match="initially pending"):
            run_case([terminal()], requested=1000, cash=amount)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("sequence", True, "sequence"),
        ("qty", 0, "qty"),
        ("qty", False, "qty"),
        ("price_cents", 10001, "tick grid"),
        ("report_id", "", "report_id"),
        ("source_id", "", "source_id"),
        ("available_at", t("09:00"), "available_at"),
        ("event_at", datetime(2026, 1, 5, 10), "aware"),
    ],
)
def test_fill_report_rejects_malformed_inputs(field: str, value: Any, reason: str) -> None:
    with pytest.raises(LifecycleError, match=reason):
        replace(fill(), **{field: value})


@pytest.mark.parametrize(
    ("hidden", "reason"),
    [
        (replace(fill(qty=2000), available_at=t("14:00")), "exceeds order"),
        (replace(fill(), available_at=t("14:00"), limits=PriceLimits(Decimal("91"), Decimal("110"))), "daily price limits"),
        (replace(terminal(), available_at=t("14:00")), "does not match"),
    ],
)
def test_hidden_state_contradictions_wait_for_availability(hidden: FillReport | TerminalReport, reason: str) -> None:
    before = run_case([hidden], requested=1000, capacity=0)
    assert before.next_state is None and before.unresolved_order_ids == ("o",)
    assert before.additional_events == ()
    with pytest.raises(LifecycleError, match=reason):
        run_case([hidden], requested=1000, capacity=0, cutoff="14:01")


def test_known_invalid_order_is_not_pending_in_an_otherwise_unknown_batch() -> None:
    state = AccountState(50_000_000, {}, t("16:00", 4), "trade_date_cash")
    orders = [OrderIntent(code, code, "BUY", 1000, 12000, t("16:00", 4)) for code in ("A", "B")]
    quotes = {"B": AuctionQuote("TRADED", 10000, LIMITS, 1000, "synthetic", "allocated")}
    batch = AuctionBatch("TWSE", "regular_open", t("08:55"), t("09:00"), "synthetic")
    args: dict[str, Any] = {"batch": batch, "costs": costs(), "max_positions": 5, "expires_at": t("13:30"), "as_of": t("13:30")}
    result = reconcile_order_lifecycle(state, orders, quotes, reports=[], **args)
    assert result.unresolved_order_ids == ("A",)
    assert result.next_state is None
    invalid = TerminalReport("B-cancel", "B", t("10:00"), t("10:00"), 1, "CANCELLED", 0, "synthetic")
    with pytest.raises(LifecycleError, match="initially pending"):
        reconcile_order_lifecycle(state, orders, quotes, reports=[invalid], **args)

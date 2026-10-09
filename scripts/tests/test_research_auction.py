from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction

import pytest

from research_core.auction import AccountState, AuctionBatch, AuctionError, AuctionQuote, CostSchedule, OrderIntent, resolve_auction_batch
from research_core.execution_prices import PriceLimits

TZ = timezone(timedelta(hours=8))
T0 = datetime(2026, 9, 8, 15, tzinfo=TZ)
BATCH = AuctionBatch("TWSE", "regular_open", datetime(2026, 9, 9, 8, 30, tzinfo=TZ), datetime(2026, 9, 9, 9, tzinfo=TZ), "s")
COSTS = CostSchedule(Fraction(1, 1000), 20, 1, "ceil", Fraction(3, 1000), 1, "floor", Fraction(0), 1, "ceil")


def order(identity: str, code: str = "A", side: str = "BUY", qty: int = 1000, price: int = 1000) -> OrderIntent:
    return OrderIntent(identity, code, side, qty, price, T0)


def quote(code: str = "A", status: str = "TRADED", price: int = 1000, cap: int = 1000) -> AuctionQuote:
    return AuctionQuote(
        status,
        price if status == "TRADED" else None,
        PriceLimits(Decimal("1"), Decimal("100")) if status == "TRADED" else None,
        cap if status == "TRADED" else None,
        "src",
        "opening_cap" if status == "TRADED" else None,
    )


def test_reservation_does_not_resize_from_cheaper_print_and_competes_cash() -> None:
    state = AccountState(1_002_000, {}, T0, "trade_date_cash")
    result = resolve_auction_batch(
        state,
        [order("a"), order("b", "B")],
        {"A": quote("A", price=5000), "B": quote("B", price=500)},
        batch=BATCH,
        costs=COSTS,
        max_positions=2,
    )
    assert result.outcomes[0].disposition == "unfilled" and result.outcomes[1].reason == "insufficient_reserved_cash"


def test_sell_cannot_fund_buy_or_free_full_book_slot() -> None:
    state = AccountState(0, {"A": 1000, "B": 1000}, T0, "settled_cash")
    result = resolve_auction_batch(
        state,
        [order("s", "A", "SELL"), order("b", "C")],
        {"A": quote("A"), "C": quote("C")},
        batch=BATCH,
        costs=COSTS,
        max_positions=2,
    )
    assert result.outcomes[1].reason in {"insufficient_reserved_cash", "max_positions_reserved"}


def test_partial_capacity_is_shared_and_residual_remains_pending() -> None:
    state = AccountState(10_000_000, {}, T0, "trade_date_cash")
    result = resolve_auction_batch(state, [order("a"), order("b")], {"A": quote(cap=1500)}, batch=BATCH, costs=COSTS, max_positions=1)
    assert [x.filled_qty for x in result.outcomes] == [1000, 0]
    assert result.next_state is not None and result.next_state.pending_order_ids == ("b",)
    assert result.outcomes[1].reason == "no_allocated_capacity"


def test_missing_data_is_not_zero_fill_state_and_halt_is_known() -> None:
    state = AccountState(10_000_000, {}, T0, "trade_date_cash")
    result = resolve_auction_batch(state, [order("a")], {}, batch=BATCH, costs=COSTS, max_positions=1)
    assert result.next_state is None and not result.state_complete
    halted = resolve_auction_batch(state, [order("a")], {"A": quote(status="HALT")}, batch=BATCH, costs=COSTS, max_positions=1)
    assert halted.next_state is not None and halted.outcomes[0].reason == "halt"


def test_validation_and_inputs_are_not_mutated() -> None:
    positions = {"A": 1000}
    state = AccountState(10_000_000, positions, T0, "trade_date_cash")
    with pytest.raises(AuctionError):
        resolve_auction_batch(state, [order("x", side="BUY"), order("y", side="SELL")], {}, batch=BATCH, costs=COSTS, max_positions=2)
    assert positions == {"A": 1000}


def test_rejected_admission_does_not_report_a_cash_reservation() -> None:
    result = resolve_auction_batch(
        AccountState(0, {}, T0, "trade_date_cash"),
        [order("no-cash")],
        {},
        batch=BATCH,
        costs=COSTS,
        max_positions=5,
    )
    assert result.outcomes[0].disposition == "rejected"
    assert result.outcomes[0].reserved_cash_cents == 0
    assert result.continuation_allowed
    assert result.next_state is not None and result.next_state.cash_cents == 0


def test_limits_price_gaps_and_observed_source_bounds_are_distinct() -> None:
    state = AccountState(10_000_000, {}, T0, "trade_date_cash")
    result = resolve_auction_batch(state, [order("a", price=2000)], {"A": quote(price=1000)}, batch=BATCH, costs=COSTS, max_positions=1)
    assert result.outcomes[0].reason == "filled"
    outside = AuctionQuote("TRADED", 2000, PriceLimits(Decimal("20"), Decimal("30")), 1000, "src", "cap")
    result = resolve_auction_batch(state, [order("a")], {"A": outside}, batch=BATCH, costs=COSTS, max_positions=1)
    assert result.outcomes[0].reason == "order_limit_outside_bounds"
    with pytest.raises(AuctionError):
        AuctionQuote("TRADED", 1000, PriceLimits(Decimal("20"), Decimal("30")), 1000, "src", "cap")


def test_odd_lot_partial_and_exact_costs_include_sell_tax_and_penalty() -> None:
    odd = AuctionBatch("TPEX", "intraday_odd", datetime(2026, 9, 9, 9, tzinfo=TZ), datetime(2026, 9, 9, 9, 10, tzinfo=TZ), "odd")
    costs = CostSchedule(Fraction(1, 1000), 20, 10, "ceil", Fraction(3, 1000), 10, "half_up", Fraction(1, 1000), 10, "floor")
    state = AccountState(100, {"A": 1}, T0, "settled_cash")
    result = resolve_auction_batch(state, [order("s", side="SELL", qty=1, price=100)], {"A": quote(price=100, cap=1)}, batch=odd, costs=costs, max_positions=1)
    outcome = result.outcomes[0]
    assert (outcome.commission_cents, outcome.tax_cents, outcome.penalty_cents) == (20, 0, 0)
    assert result.ledger_events[0]["gross_proceeds"] == 1.0


def test_partial_order_is_pending_and_blocks_next_batch_until_reconciled() -> None:
    odd = AuctionBatch("TWSE", "intraday_odd", datetime(2026, 9, 9, 9, tzinfo=TZ), datetime(2026, 9, 9, 9, 10, tzinfo=TZ), "odd")
    state = AccountState(10_000, {}, T0, "settled_cash")
    result = resolve_auction_batch(state, [order("a", qty=2, price=100)], {"A": quote(price=100, cap=1)}, batch=odd, costs=COSTS, max_positions=1)
    assert result.next_state is not None
    assert result.outcomes[0].reason == "residual_pending"
    assert result.next_state.pending_order_ids == ("a",)
    assert not result.continuation_allowed
    assert result.next_state.cash_basis == "trade_date_cash"
    with pytest.raises(AuctionError):
        resolve_auction_batch(result.next_state, [], {}, batch=BATCH, costs=COSTS, max_positions=1)


def test_existing_holding_add_does_not_consume_an_extra_slot_and_initial_overcap_fails() -> None:
    state = AccountState(10_000_000, {"A": 1000}, T0, "trade_date_cash")
    result = resolve_auction_batch(state, [order("a")], {"A": quote()}, batch=BATCH, costs=COSTS, max_positions=1)
    assert result.outcomes[0].disposition == "filled"
    with pytest.raises(AuctionError):
        resolve_auction_batch(
            AccountState(10_000_000, {"A": 1000, "B": 1000}, T0, "trade_date_cash"),
            [],
            {},
            batch=BATCH,
            costs=COSTS,
            max_positions=1,
        )


def test_exact_full_lot_sell_costs_and_trade_date_cash_basis() -> None:
    state = AccountState(0, {"A": 1000}, T0, "settled_cash")
    result = resolve_auction_batch(state, [order("s", side="SELL")], {"A": quote()}, batch=BATCH, costs=COSTS, max_positions=1)
    outcome = result.outcomes[0]
    assert (outcome.commission_cents, outcome.tax_cents, outcome.penalty_cents) == (1000, 3000, 0)
    assert result.next_state is not None and result.next_state.cash_basis == "trade_date_cash"


@pytest.mark.parametrize("venue,qty", [("regular_open", 1), ("intraday_odd", 1000)])
def test_venue_quantities_are_rejected(venue: str, qty: int) -> None:
    auction_at = datetime(2026, 9, 9, 9 if venue == "regular_open" else 9, 0 if venue == "regular_open" else 10, tzinfo=TZ)
    batch = AuctionBatch("TWSE", venue, datetime(2026, 9, 9, 8, 30, tzinfo=TZ), auction_at, "v")
    result = resolve_auction_batch(AccountState(10_000_000, {}, T0, "trade_date_cash"), [order("a", qty=qty)], {}, batch=batch, costs=COSTS, max_positions=1)
    assert result.outcomes[0].reason == "invalid_venue_quantity"


def test_batch_rejects_wrong_time_and_same_day_decision() -> None:
    with pytest.raises(AuctionError):
        AuctionBatch("TWSE", "regular_open", datetime(2026, 9, 9, 8, 30, tzinfo=TZ), datetime(2026, 9, 9, 9, 1, tzinfo=TZ), "x")
    same_day = OrderIntent("a", "A", "BUY", 1000, 1000, datetime(2026, 9, 9, 8, tzinfo=TZ))
    with pytest.raises(AuctionError):
        resolve_auction_batch(AccountState(10_000_000, {}, T0, "trade_date_cash"), [same_day], {}, batch=BATCH, costs=COSTS, max_positions=1)

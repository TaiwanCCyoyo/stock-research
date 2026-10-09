"""Synthetic simultaneous cross-market orders share pre-observation resources."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

import pytest

from research_core.auction import (
    AccountState,
    AuctionBatch,
    AuctionError,
    AuctionQuote,
    CostSchedule,
    OrderIntent,
    RoutedOrder,
    resolve_auction_batch,
    resolve_auction_cohort,
)
from research_core.execution_prices import PriceLimits
from research_core.ledger import replay_ledger


def stamp(day: int, clock: str) -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{clock}:00+08:00")


TWSE = AuctionBatch("TWSE", "regular_open", stamp(5, "08:55"), stamp(5, "09:00"), "synthetic-twse")
TPEX = AuctionBatch("TPEX", "regular_open", stamp(5, "08:55"), stamp(5, "09:00"), "synthetic-tpex")
COSTS = CostSchedule(Fraction(0), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
BOUNDS = PriceLimits(Decimal("0.01"), None)  # Supplied synthetic bounds, not ordinary-stock evidence.


def order(identifier: str, code: str, price: int, *, side: str = "BUY", qty: int = 1000) -> OrderIntent:
    return OrderIntent(identifier, code, side, qty, price, stamp(2, "16:00"))


def quote(price: int, *, capacity: int = 1000) -> AuctionQuote:
    return AuctionQuote("TRADED", price, BOUNDS, capacity, "synthetic-print", "fixed-synthetic-allocation")


def test_future_cheaper_fill_does_not_release_other_markets_reservation() -> None:
    state = AccountState(100_000_000, {}, TWSE.submitted_at, "trade_date_cash")
    routes = (RoutedOrder(order("a", "A", 60000), TWSE, COSTS), RoutedOrder(order("b", "B", 40000), TPEX, COSTS))
    observations = {(TWSE.session_id, "A"): quote(50000), (TPEX.session_id, "B"): quote(40000)}
    result = resolve_auction_cohort(state, routes, observations, max_positions=5)
    assert [item.reason for item in result.outcomes] == ["filled", "insufficient_reserved_cash"]
    assert result.outcomes[0].reserved_cash_cents == 60_002_000
    assert result.continuation_allowed and result.next_state is not None
    assert result.next_state.cash_cents == 49_998_000
    assert result.next_state.positions == {"A": 1000}
    assert result.ledger_events[0]["session_id"] == TWSE.session_id
    replayed = replay_ledger(1_000_000, result.ledger_events)
    assert replayed["cash"] == result.next_state.cash_cents / 100
    assert replayed["positions"] == dict(result.next_state.positions)
    reverse = resolve_auction_cohort(state, tuple(reversed(routes)), observations, max_positions=5)
    assert [item.order_id for item in reverse.outcomes] == ["b", "a"]
    assert reverse.next_state is not None and reverse.next_state.positions == {"B": 1000}


def test_unfilled_first_market_does_not_readmit_initially_unaffordable_order() -> None:
    routes = (RoutedOrder(order("a", "A", 60000), TWSE, COSTS), RoutedOrder(order("b", "B", 40000), TPEX, COSTS))
    result = resolve_auction_cohort(
        AccountState(100_000_000, {}, TWSE.submitted_at, "trade_date_cash"),
        routes,
        {(TWSE.session_id, "A"): AuctionQuote("HALT", None, None, None, "synthetic-halt")},
        max_positions=5,
    )
    assert [item.reason for item in result.outcomes] == ["halt", "insufficient_reserved_cash"]
    assert result.state_complete and not result.continuation_allowed
    assert result.next_state is not None and result.next_state.pending_order_ids == ("a",)
    assert result.next_state.cash_cents == 100_000_000
    assert result.ledger_events == ()


@pytest.mark.parametrize(
    "cash,holdings,cap,reason",
    [
        (0, {"A": 1000}, 5, "insufficient_reserved_cash"),
        (100_000_000, {code: 1000 for code in "ABCDE"}, 5, "max_positions_reserved"),
    ],
)
def test_same_auction_exit_cannot_finance_or_free_capacity_for_other_market(
    cash: int,
    holdings: dict[str, int],
    cap: int,
    reason: str,
) -> None:
    result = resolve_auction_cohort(
        AccountState(cash, holdings, TWSE.submitted_at, "trade_date_cash"),
        (RoutedOrder(order("sell-a", "A", 10000, side="SELL"), TWSE, COSTS), RoutedOrder(order("buy-f", "F", 10000), TPEX, COSTS)),
        {(TWSE.session_id, "A"): quote(10000), (TPEX.session_id, "F"): quote(10000)},
        max_positions=cap,
    )
    assert [item.reason for item in result.outcomes] == ["filled", reason]
    assert result.next_state is not None and "F" not in result.next_state.positions
    assert result.next_state.cash_cents == cash + 9_998_000


def test_per_route_costs_and_original_market_session_evidence_are_preserved() -> None:
    other_costs = replace(COSTS, min_commission_cents=3000)
    state = AccountState(200_000_000, {}, TWSE.submitted_at, "trade_date_cash")
    result = resolve_auction_cohort(
        state,
        (RoutedOrder(order("a", "A", 10000), TWSE, COSTS), RoutedOrder(order("b", "B", 10000), TPEX, other_costs)),
        {(TWSE.session_id, "A"): quote(10000), (TPEX.session_id, "B"): quote(10000)},
        max_positions=5,
    )
    assert [item.commission_cents for item in result.outcomes] == [2000, 3000]
    assert [event["session_id"] for event in result.ledger_events] == [TWSE.session_id, TPEX.session_id]
    assert all(event["date"] == TWSE.auction_at.isoformat() for event in result.ledger_events)
    assert result.next_state is not None and result.next_state.cash_cents == 179_995_000


def test_missing_one_markets_evidence_keeps_known_fills_diagnostic_only() -> None:
    result = resolve_auction_cohort(
        AccountState(200_000_000, {}, TWSE.submitted_at, "trade_date_cash"),
        (RoutedOrder(order("a", "A", 10000), TWSE, COSTS), RoutedOrder(order("b", "B", 10000), TPEX, COSTS)),
        {(TPEX.session_id, "B"): quote(10000)},
        max_positions=5,
    )
    assert [item.reason for item in result.outcomes] == ["missing_auction_evidence", "filled"]
    assert not result.state_complete and not result.continuation_allowed and result.next_state is None
    assert [event["code"] for event in result.ledger_events] == ["B"]


def test_children_in_same_session_share_capacity_and_single_batch_semantics() -> None:
    state = AccountState(200_000_000, {}, TWSE.submitted_at, "trade_date_cash")
    orders = (order("a1", "A", 10000), order("a2", "A", 10000))
    observations = {"A": quote(10000)}
    legacy = resolve_auction_batch(state, orders, observations, batch=TWSE, costs=COSTS, max_positions=5)
    cohort = resolve_auction_cohort(
        state, tuple(RoutedOrder(item, TWSE, COSTS) for item in orders), {(TWSE.session_id, "A"): observations["A"]}, max_positions=5
    )
    assert cohort == legacy
    assert [item.reason for item in cohort.outcomes] == ["filled", "no_allocated_capacity"]
    assert not cohort.continuation_allowed


@pytest.mark.parametrize(
    "second",
    [
        RoutedOrder(order("b", "B", 10000), replace(TPEX, submitted_at=stamp(5, "08:56")), COSTS),
        RoutedOrder(order("b", "B", 10000), AuctionBatch("TPEX", "intraday_odd", stamp(5, "08:55"), stamp(5, "09:10"), "odd"), COSTS),
        RoutedOrder(order("b", "B", 10000), replace(TPEX, session_id=TWSE.session_id), COSTS),
        RoutedOrder(order("b", "B", 10000), replace(TWSE, session_id="second-twse"), COSTS),
        RoutedOrder(order("b", "A", 10000), TPEX, COSTS),
        RoutedOrder(order("a", "B", 10000), TPEX, COSTS),
    ],
)
def test_ambiguous_or_nonsimultaneous_routes_are_rejected(second: RoutedOrder) -> None:
    with pytest.raises(AuctionError):
        resolve_auction_cohort(
            AccountState(200_000_000, {}, TWSE.submitted_at, "trade_date_cash"),
            (RoutedOrder(order("a", "A", 10000), TWSE, COSTS), second),
            {},
            max_positions=5,
        )


def test_unrecognized_quote_session_is_not_silently_treated_as_missing() -> None:
    with pytest.raises(AuctionError):
        resolve_auction_cohort(
            AccountState(200_000_000, {}, TWSE.submitted_at, "trade_date_cash"),
            (RoutedOrder(order("a", "A", 10000), TWSE, COSTS),),
            {("wrong-session", "A"): quote(10000)},
            max_positions=5,
        )


def test_empty_cohort_needs_an_explicit_single_batch_instead_of_an_invented_clock() -> None:
    state = AccountState(200_000_000, {}, TWSE.submitted_at, "trade_date_cash")
    with pytest.raises(AuctionError):
        resolve_auction_cohort(state, (), {}, max_positions=5)
    result = resolve_auction_batch(state, (), {}, batch=TWSE, costs=COSTS, max_positions=5)
    assert result.continuation_allowed and result.next_state is not None
    assert result.next_state.as_of == TWSE.auction_at
    with pytest.raises(AuctionError):
        resolve_auction_batch(replace(state, as_of=TWSE.auction_at), (), {}, batch=TWSE, costs=COSTS, max_positions=5)
    with pytest.raises(AuctionError):
        resolve_auction_batch(state, (), {"": quote(10000)}, batch=TWSE, costs=COSTS, max_positions=5)

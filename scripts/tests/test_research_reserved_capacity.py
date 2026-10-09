from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction

import pytest

from research_core.auction import AccountState, AuctionBatch, AuctionError, AuctionQuote, CostSchedule, OrderIntent, resolve_auction_batch
from research_core.execution_prices import PriceLimits
from research_core.order_lifecycle import reconcile_order_lifecycle


def at(clock: str, day: int = 5) -> datetime:
    return datetime.fromisoformat(f"2026-09-{day:02d}T{clock}:00+08:00")


BATCH = AuctionBatch("TWSE", "regular_open", at("08:55"), at("09:00"), "regular")
COSTS = CostSchedule(Fraction(0), 0, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
LIMITS = PriceLimits(Decimal("1"), Decimal("100"))


def buy(order_id: str, code: str) -> OrderIntent:
    return OrderIntent(order_id, code, "BUY", 1000, 1000, at("16:00", 4))


def quote() -> AuctionQuote:
    return AuctionQuote("TRADED", 1000, LIMITS, 1000, "fixture", "fixture-capacity")


def test_claim_only_fifth_issuer_blocks_sixth_buy() -> None:
    state = AccountState(10_000_000, {code: 1000 for code in "BCDE"}, at("08:00"), "trade_date_cash", reserved_position_codes=frozenset({"A"}))
    result = resolve_auction_batch(state, [buy("f", "F")], {"F": quote()}, batch=BATCH, costs=COSTS, max_positions=5)
    assert result.outcomes[0].reason == "max_positions_reserved"


def test_buying_already_reserved_issuer_consumes_no_new_slot() -> None:
    state = AccountState(10_000_000, {code: 1000 for code in "BCDE"}, at("08:00"), "trade_date_cash", reserved_position_codes=frozenset({"A"}))
    result = resolve_auction_batch(state, [buy("a", "A")], {"A": quote()}, batch=BATCH, costs=COSTS, max_positions=5)
    assert result.outcomes[0].disposition == "filled"
    assert result.next_state is not None and result.next_state.reserved_position_codes == frozenset({"A"})


def test_selling_reserved_original_does_not_free_a_slot() -> None:
    state = AccountState(10_000_000, {code: 1000 for code in "ABCDE"}, at("08:00"), "trade_date_cash", reserved_position_codes=frozenset({"A"}))
    sell = OrderIntent("sell-a", "A", "SELL", 1000, 1000, at("16:00", 4))
    result = resolve_auction_batch(state, [sell, buy("buy-f", "F")], {"A": quote(), "F": quote()}, batch=BATCH, costs=COSTS, max_positions=5)
    assert result.outcomes[0].disposition == "filled"
    assert result.outcomes[1].reason == "max_positions_reserved"
    assert result.next_state is not None and result.next_state.reserved_position_codes == frozenset({"A"})


def test_reserved_codes_are_frozen_and_reject_invalid_data() -> None:
    supplied = {"A"}
    state = AccountState(0, {}, at("08:00"), "trade_date_cash", reserved_position_codes=supplied)  # type: ignore[arg-type]
    supplied.add("B")
    assert state.reserved_position_codes == frozenset({"A"})
    with pytest.raises(AuctionError):
        AccountState(0, {}, at("08:00"), "trade_date_cash", reserved_position_codes=frozenset({""}))
    with pytest.raises(AuctionError):
        AccountState(0, {}, at("08:00"), "trade_date_cash", reserved_position_codes=("A",))  # type: ignore[arg-type]


def test_lifecycle_preserves_reserved_codes() -> None:
    state = AccountState(0, {}, at("08:00"), "trade_date_cash", reserved_position_codes=frozenset({"A"}))
    result = reconcile_order_lifecycle(
        state,
        [],
        {},
        batch=BATCH,
        costs=COSTS,
        max_positions=5,
        expires_at=at("13:30"),
        as_of=at("13:30"),
        reports=[],
    )
    assert result.next_state is not None and result.next_state.reserved_position_codes == frozenset({"A"})

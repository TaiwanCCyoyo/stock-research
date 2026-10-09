"""Synthetic residual fills -> ledger -> decision inputs, not strategy results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from research_core.auction import AccountState, AuctionBatch, AuctionQuote, CostSchedule, OrderIntent, buy_quantity_for_budget, resolve_auction_batch
from research_core.decision import CloseObservation, DecisionError, DecisionSnapshot, build_decision_snapshot
from research_core.execution_prices import PriceLimits
from research_core.ledger import replay_ledger
from research_core.order_lifecycle import FillReport, LifecycleResult, TerminalReport, reconcile_order_lifecycle

INITIAL_CENTS = 200_000_000
LIMITS = PriceLimits(Decimal("90"), Decimal("110"))


def at(day: int, clock: str) -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{clock}:00+08:00")


def costs() -> CostSchedule:
    # Hand-calculation schedule, not a broker's real fee contract.
    return CostSchedule(Fraction(0), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")


def context(day: int = 5) -> AuctionBatch:
    return AuctionBatch("TWSE", "regular_open", at(day, "08:55"), at(day, "09:00"), f"synthetic-{day}")


def decision(prefix: Sequence[Mapping[str, Any]], resolved: LifecycleResult) -> DecisionSnapshot:
    events = [*prefix, *resolved.initial_result.ledger_events, *resolved.additional_events]
    return build_decision_snapshot(
        initial_cash_cents=INITIAL_CENTS,
        history_start=at(2, "00:00"),
        as_of=at(5, "16:00"),
        events=events,
        session_closes=[at(2, "13:30"), at(5, "13:30")],
        calendar_id="synthetic-two-sessions",
        prices={code: CloseObservation(10000, Decimal("50"), at(5, "13:30"), at(5, "15:00"), "synthetic-close") for code in "ABCDEF"},
        execution_complete=resolved.continuation_allowed,
        execution_checkpoint_id="synthetic-explicit-terminal-prefix",
        cash_basis="trade_date_cash",
        unresolved_order_ids=resolved.unresolved_order_ids,
        max_positions=5,
    )


def test_multiple_fills_charge_one_minimum_and_feed_actual_next_decision() -> None:
    resolved = reconcile_order_lifecycle(
        AccountState(INITIAL_CENTS, {}, at(2, "16:00"), "trade_date_cash"),
        [OrderIntent("buy-A", "A", "BUY", 2000, 11000, at(2, "16:00"))],
        {"A": AuctionQuote("TRADED", 10000, LIMITS, 1000, "synthetic-open", "fixed-allocation")},
        batch=context(),
        costs=costs(),
        max_positions=5,
        expires_at=at(5, "13:30"),
        as_of=at(5, "16:00"),
        reports=[
            FillReport("fill-2", "buy-A", at(5, "10:00"), at(5, "10:01"), 1, 1000, 10100, LIMITS, "synthetic-later", "fixed-allocation"),
            TerminalReport("done", "buy-A", at(5, "10:00"), at(5, "10:01"), 2, "FILLED", 2000, "synthetic-terminal"),
        ],
    )
    assert resolved.continuation_allowed and resolved.next_state is not None
    assert [item["total"] for item in resolved.initial_result.ledger_events] == [-100020]
    assert [item["total"] for item in resolved.additional_events] == [-101000]
    assert resolved.additional_events[0]["commission_cents"] == 0
    assert resolved.next_state.cash_cents == 179_898_000
    current = decision([], resolved)
    assert current.cash_cents == resolved.next_state.cash_cents
    assert current.holdings["A"].qty == 2000
    assert current.holdings["A"].completed_closes == 1
    assert current.equity_cents == 199_898_000
    assert current.prices["B"].raw_close_cents == 10000
    assert current.prices["B"].signal_close == Decimal("50")
    assert buy_quantity_for_budget(budget_cents=40_000_000, price_cents=current.prices["B"].raw_close_cents, costs=costs(), venue="regular_open") == 3000
    # Four lots plus the 20 TWD fee exceed this exact 400k budget.


def test_partial_exit_then_cancellation_preserves_attempt_identity_and_age() -> None:
    prefix = [{"action": "BUY", "code": "A", "date": at(2, "09:00").isoformat(), "qty": 2000, "total": -200020}]
    resolved = reconcile_order_lifecycle(
        AccountState(179_998_000, {"A": 2000}, at(2, "16:00"), "trade_date_cash"),
        [OrderIntent("sell-A", "A", "SELL", 2000, 9000, at(2, "16:00"))],
        {"A": AuctionQuote("TRADED", 9500, LIMITS, 1000, "synthetic-open", "fixed-allocation")},
        batch=context(),
        costs=costs(),
        max_positions=5,
        expires_at=at(5, "13:30"),
        as_of=at(5, "16:00"),
        reports=[TerminalReport("cancel", "sell-A", at(5, "11:00"), at(5, "11:01"), 1, "CANCELLED", 1000, "synthetic-terminal")],
    )
    assert resolved.continuation_allowed and resolved.next_state is not None
    assert resolved.additional_events == ()  # Cancel is not a sale or a cash credit.
    assert resolved.next_state.cash_cents == 189_496_000
    current = decision(prefix, resolved)
    assert current.holdings["A"].qty == 1000
    assert current.holdings["A"].attempt_id == 0
    assert current.holdings["A"].entry_at == at(2, "09:00")
    assert current.holdings["A"].completed_closes == 2
    assert current.cash_cents == resolved.next_state.cash_cents
    assert current.equity_cents == 199_496_000
    replay = replay_ledger(INITIAL_CENTS / 100, [*prefix, *resolved.initial_result.ledger_events], marks={"A": 100}, max_positions=5)
    assert replay["attempts"] == []
    assert replay["positions"] == dict(resolved.next_state.positions)


def test_unknown_cancellation_blocks_decision_and_expiry_does_not_free_held_slots() -> None:
    prefix = [{"action": "BUY", "code": code, "date": at(2, "09:00").isoformat(), "qty": 1000, "total": -100020} for code in "ABCDE"]
    current = AccountState(149_990_000, dict.fromkeys("ABCDE", 1000), at(2, "16:00"), "trade_date_cash")
    intent = OrderIntent("exit-A", "A", "SELL", 1000, 9000, at(2, "16:00"))
    quotes = {"A": AuctionQuote("TRADED", 9000, LIMITS, 0, "synthetic-open", "zero-fixed-allocation")}
    terminal = TerminalReport("expiry", "exit-A", at(5, "13:30"), at(5, "16:01"), 1, "EXPIRED", 0, "synthetic-terminal")
    args: dict[str, Any] = {"batch": context(), "costs": costs(), "max_positions": 5, "expires_at": at(5, "13:30"), "reports": [terminal]}
    unknown = reconcile_order_lifecycle(current, [intent], quotes, as_of=at(5, "16:00"), **args)
    assert not unknown.continuation_allowed
    assert unknown.next_state is None
    with pytest.raises(DecisionError, match="complete"):
        decision(prefix, unknown)
    known = reconcile_order_lifecycle(current, [intent], quotes, as_of=at(5, "16:02"), **args)
    assert known.continuation_allowed and known.next_state is not None
    assert dict(known.next_state.positions) == dict(current.positions)
    assert known.next_state.cash_cents == current.cash_cents
    next_batch = resolve_auction_batch(
        known.next_state,
        [OrderIntent("buy-F", "F", "BUY", 1000, 10000, at(5, "16:05"))],
        {"F": AuctionQuote("TRADED", 10000, LIMITS, 1000, "synthetic-next-open", "fixed-allocation")},
        batch=context(6),
        costs=costs(),
        max_positions=5,
    )
    assert next_batch.outcomes[0].reason == "max_positions_reserved"
    assert next_batch.ledger_events == ()

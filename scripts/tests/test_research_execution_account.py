"""Pre-submission recorded cash/stock changes; all events and prices are synthetic."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from research_core.auction import AuctionBatch, AuctionQuote, CostSchedule, OrderIntent, resolve_auction_batch
from research_core.decision import DecisionError, ExecutionAccountSnapshot, build_execution_account_snapshot
from research_core.execution_prices import PriceLimits
from research_core.ledger import LedgerError, replay_ledger


def stamp(day: int, clock: str = "08:55") -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{clock}:00+08:00")


def prefix() -> list[dict[str, Any]]:
    return [
        {"action": "BUY", "code": "A", "date": stamp(2, "09:00").isoformat(), "qty": 1000, "total": -1_500_020},
        {
            "action": "DIVIDEND_ENTITLEMENT",
            "code": "A",
            "date": stamp(5, "08:00").isoformat(),
            "entitlement_id": "synthetic-one-distribution",
            "amount": 10_000,
            "total": 0,
        },
    ]


def payment(clock: str = "08:30") -> dict[str, Any]:
    # Explicit hypothetical bank credit, never inferred from an announcement.
    return {"action": "DIVIDEND", "code": "A", "date": stamp(6, clock).isoformat(), "entitlement_id": "synthetic-one-distribution", "total": 10_000}


def snapshot(events: list[dict[str, Any]], **overrides: Any) -> ExecutionAccountSnapshot:
    args: dict[str, Any] = {
        "initial_cash_cents": 200_000_000,
        "history_start": stamp(2, "00:00"),
        "as_of": stamp(6),
        "events": events,
        "trading_dates": [date(2026, 1, day) for day in (2, 5, 6)],
        "calendar_id": "synthetic-calendar",
        "execution_complete": True,
        "execution_checkpoint_id": "synthetic-pre-submission-prefix",
        "cash_basis": "trade_date_cash",
        "unresolved_order_ids": (),
        "max_positions": 5,
    }
    args.update(overrides)
    return build_execution_account_snapshot(**args)


def test_only_confirmed_pre_submission_payment_can_fund_the_same_fixed_intent() -> None:
    unpaid = snapshot(prefix())
    paid = snapshot([*prefix(), payment()])
    assert unpaid.account.cash_cents == 49_998_000
    assert unpaid.receivable_cents == 1_000_000
    assert paid.account.cash_cents == 50_998_000
    assert paid.receivable_cents == 0
    assert unpaid.account.positions == paid.account.positions == {"A": 1000}
    assert paid.account.cash_basis == "trade_date_cash"
    assert paid.account.as_of == stamp(6)

    intent = OrderIntent("same-prior-close-B", "B", "BUY", 1000, 50_000, stamp(5, "16:00"))
    costs = CostSchedule(Fraction(0), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
    quotes = {"B": AuctionQuote("TRADED", 50_000, PriceLimits(Decimal("450"), Decimal("550")), 1000, "synthetic-open", "fixed-test-allocation")}
    batch = AuctionBatch("TWSE", "regular_open", stamp(6), stamp(6, "09:00"), "synthetic-auction")
    denied = resolve_auction_batch(unpaid.account, [intent], quotes, batch=batch, costs=costs, max_positions=5)
    filled = resolve_auction_batch(paid.account, [intent], quotes, batch=batch, costs=costs, max_positions=5)
    assert denied.outcomes[0].reason == "insufficient_reserved_cash"
    assert denied.ledger_events == ()
    assert filled.continuation_allowed and filled.next_state is not None
    assert filled.outcomes[0].filled_qty == 1000
    assert filled.next_state.cash_cents == 996_000
    assert dict(filled.next_state.positions) == {"A": 1000, "B": 1000}
    ledger = replay_ledger(2_000_000, [*prefix(), payment(), *filled.ledger_events])
    assert ledger["cash"] == 9960
    assert ledger["dividend_receivable"] == 0
    assert ledger["positions"] == dict(filled.next_state.positions)


def test_payment_after_submission_cannot_be_borrowed_from_the_future() -> None:
    with pytest.raises(DecisionError):
        snapshot([*prefix(), payment("08:56")])
    earlier = snapshot(prefix())
    assert earlier.account.cash_cents == 49_998_000


def test_recorded_split_updates_sellable_quantity_without_prices_or_new_cash() -> None:
    split = {"action": "SPLIT", "code": "A", "date": stamp(6, "08:00").isoformat(), "total": 0, "old_qty": 1000, "new_qty": 2000}
    result = snapshot([*prefix(), split])
    assert result.account.positions == {"A": 2000}
    assert result.account.cash_cents == 49_998_000
    assert result.receivable_cents == 1_000_000
    assert result.event_count == 3


def test_two_announcement_records_cannot_be_posted_as_one_entitlement_twice() -> None:
    # Event identity must already be adjudicated; this bridge does not merge announcements.
    duplicate = dict(prefix()[1], date=stamp(5, "10:00").isoformat())
    with pytest.raises(LedgerError):
        snapshot([*prefix(), duplicate])


@pytest.mark.parametrize(
    "overrides",
    [
        {"execution_complete": False},
        {"unresolved_order_ids": ("pending-sale",)},
        {"cash_basis": "settled_cash"},
        {"initial_cash_cents": True},
        {"execution_checkpoint_id": ""},
        {"calendar_id": ""},
        {"as_of": datetime(2026, 1, 6, 8, 55)},
        {"trading_dates": [date(2026, 1, 5), date(2026, 1, 2)]},
        {"trading_dates": [date(2026, 1, 2), date(2026, 1, 2)]},
        {"trading_dates": [stamp(2)]},
        {"trading_dates": [date(2026, 1, 5), date(2026, 1, 6)]},
        {"trading_dates": [date(2026, 1, 2), date(2026, 1, 7)]},
        {"max_positions": 0},
        {"max_positions": True},
        {"max_positions": None},
    ],
)
def test_incomplete_or_invalid_prefix_metadata_is_rejected(overrides: dict[str, Any]) -> None:
    with pytest.raises((DecisionError, LedgerError)):
        snapshot(prefix(), **overrides)


@pytest.mark.parametrize(
    "events",
    [
        [dict(prefix()[0], total=-1_500_020.001)],
        [dict(prefix()[0], total=-2_000_000.01)],
        [prefix()[1], prefix()[0]],
        [prefix()[0], {"action": "DIVIDEND", "code": "A", "date": stamp(5).isoformat(), "total": 10_000}],
    ],
)
def test_invalid_money_or_event_order_cannot_create_an_execution_account(events: list[dict[str, Any]]) -> None:
    with pytest.raises((DecisionError, LedgerError)):
        snapshot(events)


def test_state_is_copied_immutable_and_does_not_claim_broker_buying_power() -> None:
    events = prefix()
    result = snapshot(events)
    events[0]["qty"] = 9999
    assert result.account.positions == {"A": 1000}
    with pytest.raises(TypeError):
        result.account.positions["B"] = 1000  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.receivable_cents = 0  # type: ignore[misc]
    assert result.account.cash_basis == "trade_date_cash"
    assert "caller" in result.evidence_basis


def test_nontrading_corporate_event_is_not_treated_as_a_fill() -> None:
    entitlement = dict(prefix()[1], date=stamp(4, "08:00").isoformat())
    result = snapshot([prefix()[0], entitlement, payment()])
    assert result.account.cash_cents == 50_998_000
    assert result.receivable_cents == 0
    with pytest.raises(DecisionError, match="fill date"):
        snapshot([dict(prefix()[0], date=stamp(4, "09:00").isoformat())])


def test_initial_cash_only_account_needs_no_closing_marks() -> None:
    result = snapshot([])
    assert result.account.cash_cents == 200_000_000
    assert result.account.positions == {}
    assert result.event_count == result.receivable_cents == 0


def test_complete_prefix_cannot_exceed_declared_position_capacity() -> None:
    second_buy = {"action": "BUY", "code": "B", "date": stamp(2, "10:00").isoformat(), "qty": 1000, "total": -10_000}
    events = [prefix()[0], second_buy, prefix()[1]]
    with pytest.raises(LedgerError):
        snapshot(events, max_positions=1)
    assert snapshot(events, max_positions=2).account.positions == {"A": 1000, "B": 1000}

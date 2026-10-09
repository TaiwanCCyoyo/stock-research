"""Actual-execution prefixes, with synthetic dates/prices and no market reads."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from research_core.auction import AccountState, AuctionBatch, AuctionQuote, CostSchedule, OrderIntent, buy_quantity_for_budget, resolve_auction_batch
from research_core.decision import CloseObservation, DecisionError, DecisionSnapshot, build_decision_snapshot
from research_core.execution_prices import PriceLimits
from research_core.ledger import LedgerError


def stamp(day: int, clock: str = "13:30") -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{clock}:00+08:00")


def observation(day: int = 6, raw: int = 10000, signal: str = "50") -> CloseObservation:
    return CloseObservation(raw, Decimal(signal), stamp(day), stamp(day, "15:00"), "synthetic-close")


def event(side: str, day: int, qty: int = 1000, total: float | None = None) -> dict[str, Any]:
    if total is None:
        total = qty * (100 if side == "SELL" else -100)
    return {"action": side, "code": "A", "date": stamp(day, "09:00").isoformat(), "qty": qty, "total": total}


def snapshot(events: list[dict[str, Any]], **overrides: Any) -> DecisionSnapshot:
    args: dict[str, Any] = {
        "initial_cash_cents": 200_000_000,
        "history_start": stamp(2, "00:00"),
        "as_of": stamp(6, "16:00"),
        "events": events,
        "session_closes": [stamp(day) for day in (2, 5, 6)],
        "calendar_id": "synthetic-jan",
        "prices": {"A": observation(), "B": observation()},
        "execution_complete": True,
        "execution_checkpoint_id": "synthetic-complete-prefix",
        "cash_basis": "trade_date_cash",
        "unresolved_order_ids": (),
        "max_positions": 5,
    }
    args.update(overrides)
    return build_decision_snapshot(**args)


def costs() -> CostSchedule:
    return CostSchedule(Fraction(0), 0, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")


def auction_events(side: str = "BUY", capacity: int = 1000):
    return resolve_auction_batch(
        AccountState(200_000_000, {} if side == "BUY" else {"A": 1000}, stamp(2, "16:00"), "trade_date_cash"),
        [OrderIntent("A-intent", "A", side, 1000, 10000, stamp(2, "16:00"))],
        {"A": AuctionQuote("TRADED", 10000, PriceLimits(Decimal("90"), Decimal("110")), capacity, "synthetic-print", "fixed-test-allocation")},
        batch=AuctionBatch("TWSE", "regular_open", stamp(5, "08:55"), stamp(5, "09:00"), "synthetic-auction"),
        costs=costs(),
        max_positions=5,
    )


def test_unrelated_fill_does_not_change_raw_sizing_price_or_signal_price() -> None:
    baseline = snapshot([])
    resolved = auction_events()
    assert resolved.continuation_allowed and resolved.next_state is not None
    after = snapshot([dict(item) for item in resolved.ledger_events])
    assert after.holdings["A"].qty == 1000
    assert after.cash_cents == resolved.next_state.cash_cents == 190_000_000
    assert after.equity_cents == baseline.equity_cents == 200_000_000
    for current in (baseline, after):
        assert current.prices["B"].signal_close == Decimal("50")
        assert current.prices["B"].raw_close_cents == 10000
        assert buy_quantity_for_budget(budget_cents=40_000_000, price_cents=current.prices["B"].raw_close_cents, costs=costs(), venue="regular_open") == 4000


def test_unfilled_exit_cannot_reset_age_or_create_a_complete_close_snapshot() -> None:
    prefix = [event("BUY", 2)]
    before = snapshot(prefix)
    resolved = auction_events("SELL", capacity=0)
    assert resolved.next_state is not None and not resolved.continuation_allowed
    assert resolved.ledger_events == ()
    with pytest.raises(DecisionError, match="unresolved"):
        snapshot(prefix, unresolved_order_ids=resolved.next_state.pending_order_ids)
    # Re-reading the same prefix does not mutate the prior holding's identity/age.
    assert snapshot(prefix).holdings["A"] == before.holdings["A"]
    assert before.holdings["A"].completed_closes == 3


def test_add_partial_exit_and_split_preserve_attempt_clock() -> None:
    events = [event("BUY", 2), event("BUY", 5, qty=500), event("SELL", 6, qty=500)]
    events.append({"action": "SPLIT", "code": "A", "date": stamp(6, "10:00").isoformat(), "total": 0, "old_qty": 1000, "new_qty": 2000})
    result = snapshot(events)
    assert result.holdings["A"].attempt_id == 0
    assert result.holdings["A"].qty == 2000
    assert result.holdings["A"].completed_closes == 3
    assert result.holdings["A"].entry_at == stamp(2, "09:00")


def test_flat_exit_and_same_symbol_reentry_get_a_new_identity_and_age() -> None:
    result = snapshot([event("BUY", 2), event("SELL", 5), event("BUY", 6)])
    assert result.holdings["A"].attempt_id == 2
    assert result.holdings["A"].completed_closes == 1
    assert snapshot([event("BUY", 2), event("SELL", 5)]).holdings == {}


def test_afterhours_entry_has_no_completed_close_on_its_entry_date() -> None:
    fill = event("BUY", 6)
    fill["date"] = stamp(6, "14:30").isoformat()
    assert snapshot([fill]).holdings["A"].completed_closes == 0


def test_receivable_is_equity_not_cash_and_paid_old_attempt_does_not_reset_new_age() -> None:
    entitlement = {"action": "DIVIDEND_ENTITLEMENT", "code": "A", "date": stamp(5, "08:00").isoformat(), "total": 0, "amount": 10000, "entitlement_id": "A-old"}
    accrued = snapshot([event("BUY", 2), entitlement], prices={"A": observation(raw=9000)})
    assert accrued.cash_cents == 190_000_000
    assert accrued.receivable_cents == 1_000_000
    assert accrued.equity_cents == 200_000_000
    events = [event("BUY", 2), entitlement, event("SELL", 5, total=90000), event("BUY", 6, total=-80000)]
    before = snapshot(events, prices={"A": observation(raw=8000)})
    payment = {"action": "DIVIDEND", "code": "A", "date": stamp(6, "12:00").isoformat(), "total": 10000, "entitlement_id": "A-old"}
    paid = snapshot([*events, payment], prices={"A": observation(raw=8000)})
    assert paid.holdings == before.holdings
    assert paid.cash_cents == before.cash_cents + 1_000_000
    assert paid.receivable_cents == 0
    assert paid.equity_cents == before.equity_cents == 200_000_000


def test_output_maps_are_copied_and_immutable() -> None:
    prices = {"A": observation()}
    result = snapshot([event("BUY", 2)], prices=prices)
    prices.clear()
    assert result.prices["A"].raw_close_cents == 10000
    with pytest.raises(TypeError):
        result.prices["B"] = observation()  # type: ignore[index]
    with pytest.raises(TypeError):
        result.holdings["B"] = result.holdings["A"]  # type: ignore[index]


@pytest.mark.parametrize(
    "overrides",
    [
        {"execution_complete": False},
        {"execution_complete": 1},
        {"execution_checkpoint_id": ""},
        {"cash_basis": "settled_cash"},
        {"initial_cash_cents": True},
        {"initial_cash_cents": 0},
        {"unresolved_order_ids": ["unknown-order"]},
        {"unresolved_order_ids": ""},
        {"session_closes": []},
        {"session_closes": [stamp(2), stamp(2), stamp(6)]},
        {"session_closes": [stamp(5), stamp(2), stamp(6)]},
        {"session_closes": [stamp(2), stamp(5)]},
        {"session_closes": [stamp(2), stamp(7)]},
        {"as_of": stamp(6, "12:00")},
        {"as_of": datetime(2026, 1, 6, 16)},
        {"history_start": stamp(6, "17:00")},
        {"calendar_id": ""},
        {"prices": {"A": observation(day=5)}},
        {"prices": {"A": replace(observation(), available_at=stamp(7, "16:00"))}},
    ],
)
def test_incomplete_or_noncausal_inputs_fail(overrides: dict[str, Any]) -> None:
    with pytest.raises(DecisionError):
        snapshot([event("BUY", 2)], **overrides)


@pytest.mark.parametrize(
    "events",
    [
        [event("BUY", 7)],
        [event("BUY", 1)],
        [event("BUY", 5), event("BUY", 2)],
        [event("BUY", 3)],  # No such session in the supplied calendar.
        [{**event("BUY", 2), "date": "2026-01-02"}],
        [{**event("BUY", 2), "date": "bad"}],
        [event("BUY", 2), {"action": "DIVIDEND", "code": "A", "date": stamp(5).isoformat(), "total": 10}],
    ],
)
def test_invalid_or_future_event_prefix_fails(events: list[dict[str, Any]]) -> None:
    with pytest.raises(DecisionError):
        snapshot(events)


def test_missing_held_mark_never_falls_back_to_signal_or_zero() -> None:
    with pytest.raises(LedgerError, match="mark"):
        snapshot([event("BUY", 2)], prices={"B": observation()})


@pytest.mark.parametrize("raw", [True, 0, -1, 10001, "10000"])
def test_raw_price_requires_positive_grid_cents(raw: Any) -> None:
    with pytest.raises(DecisionError):
        observation(raw=raw)


@pytest.mark.parametrize("signal", [Decimal("NaN"), Decimal("Infinity"), Decimal(0), 50])
def test_signal_price_requires_finite_positive_decimal(signal: Any) -> None:
    with pytest.raises(DecisionError):
        replace(observation(), signal_close=signal)


def test_signal_price_need_not_lie_on_raw_stock_grid() -> None:
    assert observation(signal="49.97314159").signal_close == Decimal("49.97314159")


def test_unknown_batch_with_one_known_fill_is_not_a_complete_prefix() -> None:
    result = resolve_auction_batch(
        AccountState(200_000_000, {}, stamp(2, "16:00"), "trade_date_cash"),
        [OrderIntent(code, code, "BUY", 1000, 10000, stamp(2, "16:00")) for code in ("A", "B")],
        {"A": AuctionQuote("TRADED", 10000, PriceLimits(Decimal("90"), Decimal("110")), 1000, "synthetic-print", "fixed-test-allocation")},
        batch=AuctionBatch("TWSE", "regular_open", stamp(5, "08:55"), stamp(5, "09:00"), "synthetic-auction"),
        costs=costs(),
        max_positions=5,
    )
    assert len(result.ledger_events) == 1 and result.next_state is None
    with pytest.raises(DecisionError, match="complete"):
        snapshot([dict(item) for item in result.ledger_events], execution_complete=result.state_complete)


@pytest.mark.parametrize("total", [-0.001, -2_000_000.01])
def test_fractional_cent_or_overspent_cash_is_not_rounded_into_a_budget(total: float) -> None:
    with pytest.raises(DecisionError):
        snapshot([event("BUY", 2, qty=1, total=total)])


def test_cent_cash_is_exact_and_explicitly_not_broker_buying_power() -> None:
    result = snapshot([event("BUY", 2, qty=1, total=-0.29)])
    assert result.cash_cents == 200_000_000 - 29
    assert result.cash_basis == "trade_date_cash"
    assert result.execution_checkpoint_id == "synthetic-complete-prefix"
    assert result.evidence_basis == "caller_asserted_prefix_and_calendar"


def test_attempt_id_is_prefix_local_not_a_cross_scenario_signal_identity() -> None:
    base = snapshot([event("BUY", 5)])
    other = {**event("BUY", 2), "code": "B"}
    shifted = snapshot([other, event("BUY", 5)])
    assert base.holdings["A"].attempt_id == 0
    assert shifted.holdings["A"].attempt_id == 1
    assert base.holdings["A"].entry_at == shifted.holdings["A"].entry_at

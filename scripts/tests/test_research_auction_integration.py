"""Fixed-event integration; no market data or strategy acceptance inference."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from typing import Any

import pytest

from research_core.attribution import mark_attempt_pnl
from research_core.auction import AccountState, AuctionBatch, AuctionError, AuctionQuote, CostSchedule, OrderIntent, resolve_auction_batch
from research_core.execution_prices import PriceLimits
from research_core.ledger import replay_ledger

INITIAL_TWD = 2_000_000


def time_on(day: str, clock: str) -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}:00+08:00")


def schedule(minimum_cents: int = 0) -> CostSchedule:
    # Deliberately synthetic fees, not a broker's quoted contract.
    return CostSchedule(
        commission_rate=Fraction(0),
        min_commission_cents=minimum_cents,
        commission_quantum_cents=1,
        commission_rounding="ceil",
        sell_tax_rate=Fraction(0),
        tax_quantum_cents=1,
        tax_rounding="ceil",
        penalty_rate=Fraction(0),
        penalty_quantum_cents=1,
        penalty_rounding="ceil",
    )


def batch(day: str, venue: str = "regular_open") -> AuctionBatch:
    clocks = {"regular_open": "09:00", "intraday_odd": "09:10", "afterhours_odd": "14:30"}
    auction_at = time_on(day, clocks[venue])
    return AuctionBatch(
        exchange="TWSE",
        venue=venue,
        submitted_at=auction_at - timedelta(minutes=5),
        auction_at=auction_at,
        session_id=f"synthetic-{day}-{venue}",
    )


def order(identity: str, code: str, side: str, qty: int, limit_cents: int, day: str) -> OrderIntent:
    return OrderIntent(
        order_id=identity,
        code=code,
        side=side,
        qty=qty,
        limit_price_cents=limit_cents,
        decision_at=time_on(day, "16:00") - timedelta(days=1),
    )


def quote(price_cents: int, shares: int) -> AuctionQuote:
    return AuctionQuote(
        status="TRADED",
        price_cents=price_cents,
        limits=PriceLimits(Decimal("0.01"), None),
        allocated_shares=shares,
        source_id="synthetic-print",
        capacity_basis="synthetic-fixed-allocation",
    )


def state_from(events: Sequence[Mapping[str, Any]], as_of: datetime) -> AccountState:
    ledger = replay_ledger(INITIAL_TWD, events, max_positions=5)
    return AccountState(
        cash_cents=round(ledger["cash"] * 100),
        positions=ledger["positions"],
        as_of=as_of,
        cash_basis="trade_date_cash",
    )


def assert_reconciled(events: Sequence[Mapping[str, Any]], state: AccountState, marks: dict[str, float]) -> dict[str, Any]:
    ledger = replay_ledger(INITIAL_TWD, events, marks=marks, max_positions=5)
    assert round(ledger["cash"] * 100) == state.cash_cents
    assert ledger["positions"] == dict(state.positions)
    pnl = mark_attempt_pnl(ledger, raw_marks=marks)
    assert INITIAL_TWD + sum(pnl.values()) == pytest.approx(ledger["marked_equity"], abs=1e-8, rel=0)
    return ledger


def test_reserved_limit_budget_is_not_recycled_after_a_cheaper_print() -> None:
    context = batch("2026-01-05")
    intents = [order(code, code, "BUY", 1000, 110_000, "2026-01-05") for code in ("A", "B")]
    current = state_from([], time_on("2026-01-02", "13:30"))
    resolved = resolve_auction_batch(
        current,
        intents,
        {"A": quote(100_000, 1000), "B": quote(100_000, 1000)},
        batch=context,
        costs=schedule(),
        max_positions=5,
    )
    assert resolved.state_complete and resolved.next_state is not None
    assert resolved.continuation_allowed
    assert dict(resolved.next_state.positions) == {"A": 1000}
    assert resolved.next_state.cash_cents == 100_000_000
    assert len(resolved.ledger_events) == 1
    assert_reconciled(list(resolved.ledger_events), resolved.next_state, {"A": 1000})


def test_regular_and_odd_children_use_distinct_prints_and_minimum_charges() -> None:
    events: list[Mapping[str, Any]] = []
    regular = resolve_auction_batch(
        state_from(events, time_on("2026-01-02", "13:30")),
        [order("A-board", "A", "BUY", 1000, 1100, "2026-01-05")],
        {"A": quote(1000, 1000)},
        batch=batch("2026-01-05"),
        costs=schedule(2000),
        max_positions=5,
    )
    assert regular.next_state is not None
    events.extend(regular.ledger_events)
    odd = resolve_auction_batch(
        regular.next_state,
        [order("A-odd", "A", "BUY", 50, 1100, "2026-01-05")],
        {"A": quote(1010, 50)},
        batch=batch("2026-01-05", "intraday_odd"),
        costs=schedule(2000),
        max_positions=5,
    )
    assert odd.next_state is not None
    events.extend(odd.ledger_events)
    assert [row["date"] for row in events] == [time_on("2026-01-05", clock).isoformat() for clock in ("09:00", "09:10")]
    assert [row["total"] for row in events] == [-10020, -525]
    ledger = assert_reconciled(events, odd.next_state, {"A": 10.1})
    assert ledger["positions"] == {"A": 1050}
    assert len(ledger["open_attempts"]) == 1
    assert ledger["marked_equity"] == INITIAL_TWD + 60


def test_tiny_partial_sale_can_cost_cash_without_disappearing_from_attribution() -> None:
    context = batch("2026-01-05", "intraday_odd")
    events: list[Mapping[str, Any]] = [
        {
            "action": "BUY",
            "code": "A",
            "date": time_on("2026-01-02", "09:10").isoformat(),
            "qty": 100,
            "total": -21,
        }
    ]
    result = resolve_auction_batch(
        state_from(events, time_on("2026-01-02", "13:30")),
        [order("A-exit", "A", "SELL", 100, 1, "2026-01-05")],
        {"A": quote(1, 1)},
        batch=context,
        costs=schedule(2000),
        max_positions=5,
    )
    assert result.next_state is not None
    events.extend(result.ledger_events)
    assert events[-1]["qty"] == 1
    assert events[-1]["gross_proceeds"] == 0.01
    assert events[-1]["cost_total"] == 20
    assert events[-1]["total"] == pytest.approx(-19.99)
    ledger = assert_reconciled(events, result.next_state, {"A": 0.01})
    assert ledger["positions"] == {"A": 99}
    assert ledger["attempts"] == []  # An open partial exit is not a completed non-hit.
    assert sum(mark_attempt_pnl(ledger, raw_marks={"A": 0.01}).values()) == pytest.approx(-40)
    assert result.next_state.pending_order_ids == ("A-exit",)
    assert not result.continuation_allowed
    with pytest.raises(AuctionError, match="pending"):
        resolve_auction_batch(
            result.next_state,
            [],
            {},
            batch=batch("2026-01-06", "intraday_odd"),
            costs=schedule(2000),
            max_positions=5,
        )


def test_known_fills_do_not_make_an_unknown_batch_safe_to_continue() -> None:
    result = resolve_auction_batch(
        state_from([], time_on("2026-01-02", "13:30")),
        [order(code, code, "BUY", 1000, 1000, "2026-01-05") for code in ("A", "B")],
        {"A": quote(1000, 1000)},
        batch=batch("2026-01-05"),
        costs=schedule(),
        max_positions=5,
    )
    assert not result.state_complete
    assert not result.continuation_allowed
    assert result.next_state is None
    assert len(result.ledger_events) == 1  # Diagnostic partial evidence only.
    assert result.ledger_events[0]["code"] == "A"


def test_paid_old_entitlement_stays_with_exited_attempt_after_new_auction_entry() -> None:
    events: list[Mapping[str, Any]] = []
    for day, side, price in [("2026-01-05", "BUY", 10000), ("2026-01-07", "SELL", 9000), ("2026-01-08", "BUY", 8000)]:
        if side == "SELL":
            events.append({
                "action": "DIVIDEND_ENTITLEMENT",
                "code": "A",
                "date": time_on("2026-01-06", "08:00").isoformat(),
                "total": 0,
                "entitlement_id": "A-old",
                "amount": 10000,
            })
        result = resolve_auction_batch(
            state_from(events, time_on(day, "08:00")),
            [order(day, "A", side, 1000, price, day)],
            {"A": quote(price, 1000)},
            batch=batch(day),
            costs=schedule(),
            max_positions=5,
        )
        assert result.next_state is not None
        events.extend(result.ledger_events)
        assert_reconciled(events, result.next_state, {"A": price / 100} if side == "BUY" else {})
    before_payment = replay_ledger(INITIAL_TWD, events, marks={"A": 80})
    events.append({
        "action": "DIVIDEND",
        "code": "A",
        "date": time_on("2026-01-09", "12:00").isoformat(),
        "total": 10000,
        "entitlement_id": "A-old",
    })
    paid_state = state_from(events, time_on("2026-01-09", "12:00"))
    ledger = assert_reconciled(events, paid_state, {"A": 80})
    assert ledger["cash"] == before_payment["cash"] + 10000
    assert ledger["marked_equity"] == before_payment["marked_equity"] == INITIAL_TWD
    assert ledger["attempts"][0]["dividend_total"] == 10000
    assert ledger["open_attempts"][0]["dividend_total"] == 0


def test_omission_fixture_reruns_admission_instead_of_deleting_a_filled_trade() -> None:
    current = state_from([], time_on("2026-01-02", "13:30"))
    intents = [order(code, code, "BUY", 1000, 110_000, "2026-01-05") for code in ("A", "B")]
    quotes = {code: quote(100_000, 1000) for code in ("A", "B")}
    baseline = resolve_auction_batch(current, intents, quotes, batch=batch("2026-01-05"), costs=schedule(), max_positions=5)
    omitted = resolve_auction_batch(current, intents[1:], quotes, batch=batch("2026-01-05"), costs=schedule(), max_positions=5)
    assert baseline.next_state is not None and omitted.next_state is not None
    assert dict(baseline.next_state.positions) == {"A": 1000}
    assert dict(omitted.next_state.positions) == {"B": 1000}
    assert [event["code"] for event in omitted.ledger_events] == ["B"]
    assert [event for event in baseline.ledger_events if event["code"] != "A"] == []
    assert_reconciled(list(omitted.ledger_events), omitted.next_state, {"B": 1000})
    # This fixed-intent unit fixture is not the required full strategy stress rerun.


def test_nonzero_execution_penalty_is_separate_from_the_print_and_charged_once() -> None:
    costs = CostSchedule(
        commission_rate=Fraction(1, 1000),
        min_commission_cents=2000,
        commission_quantum_cents=1,
        commission_rounding="ceil",
        sell_tax_rate=Fraction(1, 100),
        tax_quantum_cents=1,
        tax_rounding="ceil",
        penalty_rate=Fraction(1, 200),
        penalty_quantum_cents=1,
        penalty_rounding="ceil",
    )
    events: list[Mapping[str, Any]] = []
    final_state = state_from(events, time_on("2026-01-02", "13:30"))
    for day, side, print_cents in [("2026-01-05", "BUY", 10000), ("2026-01-06", "SELL", 11000)]:
        result = resolve_auction_batch(
            final_state,
            [order(day, "A", side, 1000, print_cents, day)],
            {"A": quote(print_cents, 1000)},
            batch=batch(day),
            costs=costs,
            max_positions=5,
        )
        assert result.continuation_allowed and result.next_state is not None
        assert result.outcomes[0].price_cents == print_cents
        final_state = result.next_state
        events.extend(result.ledger_events)
    assert [row["price"] for row in events] == [100, 110]
    assert [row["commission_cents"] for row in events] == [10000, 11000]
    assert [row["tax_cents"] for row in events] == [0, 110000]
    assert [row["penalty_cents"] for row in events] == [50000, 55000]
    assert [row["total"] for row in events] == [-100600, 108240]
    ledger = assert_reconciled(events, final_state, {})
    assert ledger["attempts"][0]["net_pnl"] == 7640
    assert ledger["cash"] == INITIAL_TWD + 7640

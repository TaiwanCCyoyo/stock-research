"""Small chronological counterfactual fixture, not a production stress dispatcher.

Every price, ranking and cost below is synthetic. Recommendations receive only
the current decision snapshot. Each arm reruns recommendations, sizing and fills.
No randomness, historical data, candidate ranking or acceptance thresholds.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction
from typing import Any

from research_core.auction import AccountState, AuctionBatch, AuctionQuote, CostSchedule, OrderIntent, buy_quantity_for_budget
from research_core.decision import CloseObservation, DecisionSnapshot, build_decision_snapshot
from research_core.execution_prices import PriceLimits
from research_core.order_lifecycle import reconcile_order_lifecycle

INITIAL_CENTS = 200_000_000
DAYS = (2, 5, 6, 7, 8)  # Explicit fixture trading calendar, not a holiday inference.
RANKED_CANDIDATE = {2: "A", 5: "B", 6: "A"}
RAW_CLOSE = {
    2: {"A": 100000, "B": 100000},
    5: {"A": 100000, "B": 100000},
    6: {"A": 90000, "B": 105000},
    7: {"A": 95000, "B": 110000},
    8: {"A": 110000, "B": 110000},
}
OPEN = {5: {"A": 100000, "B": 100000}, 6: {"A": 90000, "B": 100000}, 7: {"A": 95000, "B": 110000}, 8: {"A": 110000, "B": 110000}}
COSTS = CostSchedule(Fraction(0), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
UNBOUNDED = PriceLimits(Decimal("0.01"), None)  # Synthetic supplied bounds, never an ordinary-day market claim.


def stamp(day: int, time: str = "16:00") -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{time}:00+08:00")


def identity(day: int, code: str) -> str:
    return f"fixture:{day}:{code}:buy:1"


def recommendations(snapshot: DecisionSnapshot, candidate: str | None) -> tuple[OrderIntent, ...]:
    """Toy one-lot entry rule; no future frame, result or stress label is passed."""
    if candidate is None or candidate in snapshot.holdings:
        return ()
    # All fixture prices admit an exact on-grid 10% limit. Not a general limit calculator.
    limit = snapshot.prices[candidate].raw_close_cents * 11 // 10
    quantity = min(1000, buy_quantity_for_budget(budget_cents=snapshot.cash_cents, price_cents=limit, costs=COSTS, venue="regular_open"))
    if not quantity:
        return ()
    return (OrderIntent(identity(snapshot.as_of.day, candidate), candidate, "BUY", quantity, limit, snapshot.as_of),)


def snapshot(day: int, events: list[Mapping[str, Any]]) -> DecisionSnapshot:
    return build_decision_snapshot(
        initial_cash_cents=INITIAL_CENTS,
        history_start=stamp(2, "00:00"),
        as_of=stamp(day),
        events=events,
        session_closes=[stamp(item, "13:30") for item in DAYS if item <= day],
        calendar_id="synthetic-four-open-sessions",
        prices={
            code: CloseObservation(raw, Decimal(raw) / 200, stamp(day, "13:30"), stamp(day, "15:00"), "fixture-close") for code, raw in RAW_CLOSE[day].items()
        },
        execution_complete=True,  # run() asserts each actual lifecycle result first.
        execution_checkpoint_id=f"fixture-closed-prefix-{day}",
        cash_basis="trade_date_cash",
        unresolved_order_ids=(),
        max_positions=5,
    )


@dataclass
class Run:
    events: list[Mapping[str, Any]]
    decisions: dict[int, tuple[OrderIntent, ...]]
    outcomes: dict[int, tuple[str, ...]]
    snapshots: dict[int, DecisionSnapshot]
    outstanding: tuple[OrderIntent, ...]


def run(*, omit: frozenset[str] = frozenset(), extra_delay: int = 0) -> Run:
    assert isinstance(extra_delay, int) and not isinstance(extra_delay, bool) and extra_delay >= 0
    events: list[Mapping[str, Any]] = []
    decisions: dict[int, tuple[OrderIntent, ...]] = {}
    outcomes: dict[int, tuple[str, ...]] = {}
    snapshots: dict[int, DecisionSnapshot] = {}
    queued: list[tuple[int, OrderIntent]] = []
    for index, day in enumerate(DAYS):
        expected: AccountState | None = None
        if index:
            before = snapshots[DAYS[index - 1]]
            submitted = [intent for due_index, intent in queued if due_index == index]
            queued = [(due_index, intent) for due_index, intent in queued if due_index != index]
            resolved = reconcile_order_lifecycle(
                AccountState(before.cash_cents, {code: item.qty for code, item in before.holdings.items()}, before.as_of, "trade_date_cash"),
                submitted,
                {code: AuctionQuote("TRADED", price, UNBOUNDED, 1000, "fixture-open", "fixed-test-allocation") for code, price in OPEN[day].items()},
                batch=AuctionBatch("TWSE", "regular_open", stamp(day, "08:55"), stamp(day, "09:00"), f"fixture-session-{day}"),
                costs=COSTS,
                max_positions=5,
                expires_at=stamp(day, "13:30"),
                as_of=stamp(day),
                reports=[],  # These fixtures admit fills or explicit admission rejections only.
            )
            assert resolved.continuation_allowed and resolved.next_state is not None
            expected = resolved.next_state
            events.extend(resolved.initial_result.ledger_events)
            events.extend(resolved.additional_events)
            outcomes[day] = tuple(item.reason for item in resolved.initial_result.outcomes)
        current = snapshot(day, events)
        if expected is not None:
            assert current.cash_cents == expected.cash_cents
            assert {code: item.qty for code, item in current.holdings.items()} == dict(expected.positions)
        snapshots[day] = current
        decisions[day] = recommendations(current, RANKED_CANDIDATE.get(day))
        for intent in decisions[day]:
            if intent.order_id not in omit:
                queued.append((index + 1 + extra_delay, intent))
    return Run(events, decisions, outcomes, snapshots, tuple(intent for _, intent in queued))


def test_omission_reruns_recommendations_cash_sizing_and_future_entries() -> None:
    baseline = run()
    omitted = run(omit=frozenset({identity(2, "A")}))
    assert [event["order_id"] for event in baseline.events] == [identity(2, "A")]
    assert [event["order_id"] for event in omitted.events] == [identity(5, "B"), identity(6, "A")]
    assert baseline.decisions[5] == ()  # Less than the reserved one-lot budget after A.
    assert [item.code for item in omitted.decisions[5]] == ["B"]
    assert omitted.events[-1]["date"] == stamp(7, "09:00").isoformat()
    assert omitted.snapshots[8].cash_cents == 4_996_000
    assert omitted.snapshots[8].equity_cents == 224_996_000
    assert baseline.snapshots[8].cash_cents == 99_998_000
    assert baseline.snapshots[8].equity_cents == 209_998_000
    assert baseline.outstanding == omitted.outstanding == ()
    # Deleting the old A trade produces neither B nor the distinct later A entry.
    assert [event for event in baseline.events if event["order_id"] != identity(2, "A")] == []


def test_extra_day_delay_uses_later_print_but_keeps_submitted_quantity_and_limit() -> None:
    baseline = run()
    delayed = run(extra_delay=1)
    assert baseline.decisions[2] == delayed.decisions[2]
    assert delayed.decisions[2][0].limit_price_cents == 110000
    assert delayed.decisions[2][0].qty == 1000
    assert delayed.events[0]["date"] == stamp(6, "09:00").isoformat()
    assert delayed.events[0]["price"] == 900
    assert [item.code for item in delayed.decisions[5]] == ["B"]
    # A's cheaper delayed fill leaves 1,099,980 TWD, still 40 TWD short of
    # the original B limit reservation of 1,100,020. Do not use future proceeds
    # or resize an already-submitted request at its actual print.
    assert delayed.snapshots[6].cash_cents == 109_998_000
    assert delayed.outcomes[7] == ("insufficient_reserved_cash",)
    assert [event["order_id"] for event in delayed.events] == [identity(2, "A")]
    assert delayed.snapshots[8].equity_cents == 219_998_000


def test_delayed_intents_beyond_fixture_horizon_remain_explicitly_outstanding() -> None:
    delayed = run(extra_delay=3)
    assert delayed.events[0]["date"] == stamp(8, "09:00").isoformat()
    assert [intent.order_id for intent in delayed.outstanding] == [identity(5, "B"), identity(6, "A")]
    # The test harness does not label these missed/expired or claim a finished stress run.

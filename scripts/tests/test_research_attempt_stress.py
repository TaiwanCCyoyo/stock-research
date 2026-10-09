"""Hand-calculated full reruns, not market strategy results."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from research_core.attempt_stress import StressInputs, run_best_attempt_stresses
from research_core.auction import AuctionBatch, AuctionQuote, OrderIntent
from research_core.chronology import (
    ActionRule,
    ChronologyError,
    CorporateEvidence,
    DayFrame,
    DecisionContext,
    DecisionRule,
    ExecutionEvidence,
    ExecutionWindow,
    PriorCloseRequest,
    Scenario,
    SessionRoute,
)
from research_core.decision import CloseObservation, ExecutionAccountSnapshot
from scripts.tests import test_research_causal_scenarios as market
from scripts.tests import test_research_chronology as fixture


def inputs(*, contingent_add: bool = True) -> StressInputs:
    # A: buy 100, add 100, partial sell 200, final sell 200 = +199,920.
    # Later A: buy 100, sell 110 = +9,960, not part of first attempt.
    days = (2, 5, 6, 7, 8, 9, 12)
    prices = {2: 10000, 5: 10000, 6: 10000, 7: 20000, 8: 20000, 9: 10000, 12: 11000}
    frames = []
    for day in days:
        batch = AuctionBatch("TWSE", "regular_open", market.stamp(day, "08:55"), market.stamp(day, "09:00"), f"session-{day}")
        window = ExecutionWindow(f"window-{day}", (SessionRoute(batch, market.COSTS),), market.stamp(day, "13:30"), market.stamp(day))
        close = CloseObservation(prices[day], Decimal(prices[day]) / 100, market.stamp(day, "13:30"), market.stamp(day, "15:00"), "invented-close")
        frames.append(DayFrame(date(2026, 1, day), close.observed_at, market.stamp(day), {"A": close}, (window,)))

    def factory() -> DecisionRule:
        def decide(context: DecisionContext) -> fixture.Requests:
            snap = context.snapshot
            day = snap.as_of.day
            held = "A" in snap.holdings
            action = None
            if day in {2, 8} and not held or day == 5 and (held or not contingent_add):
                action = "BUY"
            elif day in {6, 7, 9} and held:
                action = "SELL"
            if action is None:
                return ()
            order = OrderIntent(f"A-{day}-{action}", "A", action, 1000, 30000 if action == "BUY" else 100, snap.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open"),)

        return decide

    def execution(window: ExecutionWindow, account: ExecutionAccountSnapshot, routes: fixture.Routes) -> ExecutionEvidence:
        quotes = {
            (route.batch.session_id, "A"): AuctionQuote("TRADED", prices[window.as_of.day], market.UNBOUNDED, 1000, "invented-fill", "fixed-test-allocation")
            for route in routes
        }
        return ExecutionEvidence(window.window_id, quotes, (), True, True)

    return StressInputs(
        200_000_000,
        5,
        market.stamp(2, "00:00"),
        "synthetic-initial",
        tuple(frames),
        "synthetic-seven-days",
        True,
        factory,
        lambda: execution,
        lambda: fixture.corporate,
    )


@pytest.mark.parametrize("contingent_add", [True, False])
def test_best_attempt_suppresses_all_its_buys_but_preserves_same_stock_reentry(contingent_add: bool) -> None:
    result = run_best_attempt_stresses(inputs(contingent_add=contingent_add), counts=(1, 3))
    assert result.baseline.status == "complete"
    assert [item.net_pnl_cents for item in result.ranked_closed_attempts] == [19_992_000, 996_000]
    target = result.arms[0].targets[0]
    assert target.buy_order_ids == frozenset({"A-2-BUY", "A-5-BUY"})
    arm = result.arms[0].result
    assert arm is not None and arm.status == "complete"
    assert [event["order_id"] for event in arm.events] == ["A-8-BUY", "A-9-SELL"]
    assert arm.snapshots[-1].equity_cents == 200_996_000
    assert arm.unmatched_omission_ids == (frozenset({"A-5-BUY"}) if contingent_add else frozenset())
    assert result.arms[1].result is None and result.arms[1].unavailable_reason == "insufficient_closed_attempts"


def test_unmatched_required_targets_still_make_run_incomplete() -> None:
    config = inputs()
    result = config.run(Scenario("typo", frozenset({"missing", "A-2-BUY"}), 0, frozenset({"missing"})))
    assert result.stop_reason == "unapplied_omission_targets"
    with pytest.raises(ChronologyError, match="subset"):
        Scenario("bad", frozenset(), 0, frozenset({"missing"}))


def test_released_cash_and_changed_holdings_create_a_new_alternative_trade() -> None:
    config = inputs()

    def factory() -> DecisionRule:
        original = config.decision_factory()

        def decide(context: DecisionContext) -> fixture.Requests:
            snap = context.snapshot
            side = None
            if snap.as_of.day == 5 and "A" not in snap.holdings:
                side = "BUY"
            elif snap.as_of.day == 6 and "B" in snap.holdings:
                side = "SELL"
            if side is not None:
                order = OrderIntent(f"B-{snap.as_of.day}-{side}", "B", side, 1000, 30000 if side == "BUY" else 100, snap.as_of)
                return (PriorCloseRequest(order, "TWSE", "regular_open"),)
            return fixture.advised(original(context))

        return decide

    def execution(window: ExecutionWindow, account: ExecutionAccountSnapshot, routes: fixture.Routes) -> ExecutionEvidence:
        if routes[0].order.code == "A":
            return config.execution_factory()(window, account, routes)
        price = 10000 if window.as_of.day == 6 else 13000
        quote = AuctionQuote("TRADED", price, market.UNBOUNDED, 1000, "invented-B", "fixed-allocation")
        return ExecutionEvidence(window.window_id, {(route.batch.session_id, "B"): quote for route in routes}, (), True, True)

    frames = tuple(replace(frame, prices={**frame.prices, "B": frame.prices["A"]}) for frame in config.frames)
    result = run_best_attempt_stresses(replace(config, frames=frames, decision_factory=factory, execution_factory=lambda: execution), counts=(1,))
    arm = result.arms[0].result
    assert arm is not None and arm.status == "complete"
    assert [event["order_id"] for event in arm.events] == ["B-5-BUY", "B-6-SELL", "A-8-BUY", "A-9-SELL"]
    assert arm.snapshots[-1].equity_cents == 203_992_000
    assert arm.snapshots[-1].equity_cents != result.baseline.snapshots[-1].equity_cents - result.arms[0].targets[0].net_pnl_cents


def test_reused_id_cannot_suppress_a_different_decision() -> None:
    config = inputs()
    count = 0

    def factory() -> DecisionRule:
        nonlocal count
        count += 1
        current = count
        rule = config.decision_factory()

        def changed(context: DecisionContext) -> fixture.Requests:
            requests = fixture.advised(rule(context))
            if current > 1 and context.snapshot.as_of.day == 2:
                return tuple(replace(request, intent=replace(request.intent, code="B")) for request in requests)
            return requests

        return changed

    with pytest.raises(ChronologyError, match="decision identity"):
        run_best_attempt_stresses(replace(config, decision_factory=factory), counts=(1,))


def test_incomplete_baseline_does_not_select_or_run_stress() -> None:
    config = replace(inputs(), corporate_factory=lambda: lambda since, until, prefix: CorporateEvidence("unknown", (), False))
    result = run_best_attempt_stresses(config, counts=(1,))
    assert result.baseline.status == "incomplete"
    assert not result.ranked_closed_attempts and result.arms[0].unavailable_reason == "baseline_incomplete"


def test_open_attempts_are_visible_but_not_ranked_as_completed() -> None:
    config = inputs()

    def factory() -> ActionRule:
        rule = config.decision_factory()
        return lambda context: () if context.snapshot.as_of.day == 9 else rule(context)

    result = run_best_attempt_stresses(replace(config, decision_factory=factory), counts=(1, 3))
    assert result.baseline.status == "complete"
    assert len(result.ranked_closed_attempts) == 1
    assert result.open_attempt_ids == (4,)
    assert result.arms[1].unavailable_reason == "insufficient_closed_attempts"


def test_best_three_can_causally_remove_later_entries_without_becoming_incomplete() -> None:
    config = inputs()
    factories: list[str] = []

    def factory() -> DecisionRule:
        factories.append("fresh")

        def decide(context: DecisionContext) -> fixture.Requests:
            snap = context.snapshot
            day = snap.as_of.day
            held = "A" in snap.holdings
            side = None
            if day == 2 or day in {6, 8} and not held and snap.cash_cents > 200_000_000:
                side = "BUY"
            elif day in {5, 7, 9} and held:
                side = "SELL"
            if side is None:
                return ()
            return (PriorCloseRequest(OrderIntent(f"A-{day}-{side}", "A", side, 1000, 30000 if side == "BUY" else 100, snap.as_of), "TWSE", "regular_open"),)

        return decide

    def execution(window: ExecutionWindow, account: ExecutionAccountSnapshot, routes: fixture.Routes) -> ExecutionEvidence:
        prices = {5: 10000, 6: 15000, 7: 10000, 8: 20000, 9: 10000, 12: 11000}
        quote = AuctionQuote("TRADED", prices[window.as_of.day], market.UNBOUNDED, 1000, "fixture", "invented-allocation")
        return ExecutionEvidence(window.window_id, {(route.batch.session_id, "A"): quote for route in routes}, (), True, True)

    config = replace(config, decision_factory=factory, execution_factory=lambda: execution)
    result = run_best_attempt_stresses(config, counts=(1, 3))
    assert len(factories) == 3
    assert [item.entry_order_id for item in result.ranked_closed_attempts] == ["A-6-BUY", "A-2-BUY", "A-8-BUY"]
    one = result.arms[0].result
    three = result.arms[1].result
    assert one is not None and three is not None
    assert one.status == three.status == "complete"
    assert one.events and three.events == ()
    assert three.matched_omission_ids == frozenset({"A-2-BUY"})
    assert three.unmatched_omission_ids == frozenset({"A-6-BUY", "A-8-BUY"})
    assert three.scenario.required_omission_ids == frozenset({"A-2-BUY"})


@pytest.mark.parametrize("paid", [True, False])
def test_old_dividend_ranking_is_unchanged_by_payment_after_same_stock_reentry(paid: bool) -> None:
    config = inputs()
    frames = tuple(
        replace(frame, windows=tuple(replace(window, as_of=market.stamp(frame.trade_date.day, "13:30")) for window in frame.windows)) for frame in config.frames
    )

    def corporate(since: datetime, until: datetime, prefix: fixture.Prefix) -> CorporateEvidence:
        events: list[dict[str, object]] = []
        entitled_at = market.stamp(6, "15:30")
        paid_at = market.stamp(9, "15:30")
        if since < entitled_at <= until and any(event.get("order_id") == "A-2-BUY" for event in prefix):
            events.append({
                "action": "DIVIDEND_ENTITLEMENT",
                "code": "A",
                "date": entitled_at.isoformat(),
                "total": 0,
                "amount": 20000,
                "entitlement_id": "old-A",
            })
        if paid and since < paid_at <= until and any(event.get("entitlement_id") == "old-A" for event in prefix):
            events.append({"action": "DIVIDEND", "code": "A", "date": paid_at.isoformat(), "total": 20000, "entitlement_id": "old-A"})
        return CorporateEvidence("invented-corporate", tuple(events), True)

    result = run_best_attempt_stresses(replace(config, frames=frames, corporate_factory=lambda: corporate), counts=(1,))
    assert [item.net_pnl_cents for item in result.ranked_closed_attempts] == [21_992_000, 996_000]
    assert result.ranked_closed_attempts[0].unpaid_receivable_cents == (0 if paid else 2_000_000)
    arm = result.arms[0].result
    assert arm is not None and arm.status == "complete"
    assert all(event["action"] in {"BUY", "SELL"} for event in arm.events)


@pytest.mark.parametrize("counts", [(), (0,), (True,), (1, 1)])
def test_invalid_counts_are_not_partial_or_coerced_runs(counts: tuple[int, ...]) -> None:
    with pytest.raises(ChronologyError):
        run_best_attempt_stresses(inputs(), counts=counts)

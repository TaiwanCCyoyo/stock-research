"""Order actions: withdrawal before submission, terminal history, lineage, corporate seam.

Three things the runner could not previously express, each a concrete failure rather than a
missing convenience:

- a request fixed at one decision could not be withdrawn before the session it was waiting for,
  so a rule that changed its mind had to let the stale order trade;
- an order that ended -- filled, rejected, expired, cancelled -- told the next decision nothing,
  so a retry could only be a brand new order with no link to what it was retrying, and nothing
  stopped it re-requesting the whole original size after a partial fill;
- a corporate action that changed a share count was applied to positions while pending orders
  kept their frozen quantity and limit, so a forward split left unintended residual shares and a
  reverse split turned a legal exit into one the auction rejects for an unexplained reason.

Every fixture here is synthetic. No market data, no strategy claim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from fractions import Fraction
from typing import Any

import pytest

from research_core.auction import AuctionQuote, OrderIntent, RoutedOrder
from research_core.chronology import (
    ActionRule,
    ChronologyError,
    ChronologyResult,
    CorporateEvidence,
    DecisionContext,
    ExecutionEvidence,
    ExecutionWindow,
    PendingRequest,
    PriorCloseRequest,
    Scenario,
)
from research_core.decision import ExecutionAccountSnapshot
from research_core.order_actions import (
    CancelRequest,
    OrderActionError,
    OrderLineage,
    PendingResolution,
)
from research_core.order_lifecycle import TerminalReport
from research_core.signals import SignalIdentity, SignalOmission
from scripts.tests import test_research_causal_scenarios as fixture
from scripts.tests import test_research_chronology as harness

Prefix = tuple[Mapping[str, Any], ...]
Generated = Sequence[PriorCloseRequest | CancelRequest]
Routes = tuple[RoutedOrder, ...]

BUY_A = fixture.identity(2, "A")
SELL_A = "fixture:5:A:sell:1"


def sell_signal(at: datetime) -> SignalIdentity:
    return SignalIdentity(signal_id="SELL:A", code="A", side="SELL", origin_at=at)


def buy_and_exit_factory(
    *,
    sell_on: int = 5,
    limit_cents: int = 90_000,
    with_signal: bool = False,
    buy_qty: int = 1000,
) -> ActionRule:
    """Buy A on the first decision, then advise one exit. Deliberately tiny.

    `buy_qty` exists because a partial fill is impossible below two board lots: `regular_open`
    floors an allocation to whole lots, so a 1,000-share order either fills completely or not at
    all. Tests that need a residual buy three lots and allocate one.
    """

    def decide(context: DecisionContext) -> Generated:
        snapshot = context.snapshot
        day = snapshot.as_of.day
        if day == 2:
            order = OrderIntent(BUY_A, "A", "BUY", buy_qty, 110_000, snapshot.as_of)
            signal = SignalIdentity("BUY:A", "A", "BUY", snapshot.as_of) if with_signal else None
            return (PriorCloseRequest(order, "TWSE", "regular_open", signal),)
        if day == sell_on and "A" in snapshot.holdings:
            order = OrderIntent(SELL_A, "A", "SELL", snapshot.holdings["A"].qty, limit_cents, snapshot.as_of)
            signal = sell_signal(snapshot.as_of) if with_signal else None
            return (PriorCloseRequest(order, "TWSE", "regular_open", signal),)
        return ()

    return decide


def quotes_for(routes: Routes, prices: Mapping[str, int], *, allocation: int = 1000) -> dict[tuple[str, str], AuctionQuote]:
    return {
        (route.batch.session_id, route.order.code): AuctionQuote(
            "TRADED", prices[route.order.code], fixture.UNBOUNDED, allocation, "fixture-open", "fixed-test-allocation"
        )
        for route in routes
    }


def execution_with(
    *,
    allocation: Mapping[int, int] | None = None,
    reports: Mapping[int, tuple[TerminalReport, ...]] | None = None,
    prices: Mapping[int, Mapping[str, int]] | None = None,
):
    """An execution provider whose per-day allocation, price and receipts are stated explicitly."""
    allocation = {} if allocation is None else allocation
    reports = {} if reports is None else reports
    prices = fixture.OPEN if prices is None else prices

    def provide(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Routes) -> ExecutionEvidence:
        day = window.as_of.day
        return ExecutionEvidence(
            f"execution-{day}",
            quotes_for(routes, prices[day], allocation=allocation.get(day, 1000)),
            reports.get(day, ()),
            True,
            True,
        )

    return provide


def split_provider(*, at_day: int, at_time: str, code: str = "A", ratio: int = 2):
    """A corporate provider that reports one split, dated exactly where the fixture wants it."""
    moment = fixture.stamp(at_day, at_time)

    def provide(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        if not since < moment <= until:
            return CorporateEvidence(f"no-corporate-events-{until.isoformat()}", (), True)
        held = 0
        for event in prefix:
            if event.get("code") != code:
                continue
            if event.get("action") == "BUY":
                held += int(event["qty"])
            elif event.get("action") == "SELL":
                held -= int(event["qty"])
            elif event.get("action") == "SPLIT":
                held = int(event["new_qty"])
        if held <= 0:
            return CorporateEvidence(f"split-not-held-{until.isoformat()}", (), True)
        new_qty = held * ratio if ratio > 0 else held
        return CorporateEvidence(
            f"split-{moment.isoformat()}",
            (
                {
                    "action": "SPLIT",
                    "code": code,
                    "date": moment.isoformat(),
                    "total": 0,
                    "old_qty": held,
                    "new_qty": new_qty,
                    "qty": new_qty - held,
                    "evidence_basis": "fixture: a dated split, not a market record",
                },
            ),
            True,
        )

    return provide


def halved_provider(*, at_day: int, at_time: str, code: str = "A"):
    """A reverse split: the share count halves, which a stale exit order would oversell."""
    moment = fixture.stamp(at_day, at_time)

    def provide(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        if not since < moment <= until:
            return CorporateEvidence(f"no-corporate-events-{until.isoformat()}", (), True)
        held = 0
        for event in prefix:
            if event.get("code") != code:
                continue
            if event.get("action") == "BUY":
                held += int(event["qty"])
            elif event.get("action") == "SELL":
                held -= int(event["qty"])
            elif event.get("action") == "SPLIT":
                held = int(event["new_qty"])
        if held <= 0:
            return CorporateEvidence(f"split-not-held-{until.isoformat()}", (), True)
        return CorporateEvidence(
            f"reverse-split-{moment.isoformat()}",
            (
                {
                    "action": "SPLIT",
                    "code": code,
                    "date": moment.isoformat(),
                    "total": 0,
                    "old_qty": held,
                    "new_qty": held // 2,
                    "qty": held // 2 - held,
                    "evidence_basis": "fixture: a dated reverse split, not a market record",
                },
            ),
            True,
        )

    return provide


def frames_with_an_afternoon() -> tuple[Any, ...]:
    """The shared frames, but with each window closing at 13:30 instead of at the decision.

    The base harness sets a window's cutoff equal to the decision timestamp, which leaves no
    interval between them and so no corporate call there. A split dated in the afternoon needs
    that interval to exist before it can be consumed by the pre-decision call -- which is exactly
    the timing that a conflict check scoped to the current window would miss.
    """
    from dataclasses import replace

    prepared = []
    for frame in harness.frames():
        windows = tuple(replace(window, as_of=fixture.stamp(frame.trade_date.day, "13:30")) for window in frame.windows)
        prepared.append(replace(frame, windows=windows))
    return tuple(prepared)


def run(**overrides: Any) -> ChronologyResult:
    return harness.run(**overrides)


def terminal(order_id: str, day: int, *, status: str, filled: int, sequence: int = 1) -> TerminalReport:
    return TerminalReport(
        report_id=f"{status.lower()}-{order_id}-{day}",
        order_id=order_id,
        event_at=fixture.stamp(day, "13:30"),
        available_at=fixture.stamp(day, "13:30"),
        sequence=sequence,
        status=status,
        cumulative_filled_qty=filled,
        source_id="fixture-broker",
    )


# --------------------------------------------------------------------------------------------
# Withdrawal before submission: the order was never sent, so no broker receipt exists to quote.
# --------------------------------------------------------------------------------------------


def test_a_request_can_be_withdrawn_before_the_session_it_was_waiting_for() -> None:
    """Under a delay the day-2 buy is still queued at day 5, and the rule may take it back."""

    def factory() -> ActionRule:
        base = buy_and_exit_factory()

        def decide(context: DecisionContext) -> Generated:
            waiting = [item for item in context.pending if item.request.intent.order_id == BUY_A]
            if waiting and context.snapshot.as_of.day == 5:
                return (CancelRequest(BUY_A, "fixture: the rule changed its mind before submission", context.snapshot.as_of),)
            return base(context)

        return decide

    result = run(decision_factory=factory, scenario=Scenario("delay-one", frozenset(), 1))
    assert result.status == "complete"
    assert result.pending == ()
    assert not any(event.get("order_id") == BUY_A for event in result.events), "a withdrawn order cannot trade"

    ended = {record.order_id: record for record in result.terminations}
    assert ended[BUY_A].status == "WITHDRAWN"
    assert ended[BUY_A].provenance == "decision"
    assert ended[BUY_A].filled_qty == 0
    assert ended[BUY_A].residual_qty == 1000
    assert ended[BUY_A].terminated_at == fixture.stamp(5)


def test_a_withdrawal_is_never_dressed_up_as_a_broker_terminal() -> None:
    """`WITHDRAWN` is a decision-side fact and must not borrow the receipt vocabulary."""

    def factory() -> ActionRule:
        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day == 2:
                order = OrderIntent(BUY_A, "A", "BUY", 1000, 110_000, context.snapshot.as_of)
                return (PriorCloseRequest(order, "TWSE", "regular_open"),)
            if any(item.request.intent.order_id == BUY_A for item in context.pending):
                return (CancelRequest(BUY_A, "fixture: withdrawn", context.snapshot.as_of),)
            return ()

        return decide

    result = run(decision_factory=factory, scenario=Scenario("delay-one", frozenset(), 1))
    withdrawn = next(record for record in result.terminations if record.order_id == BUY_A)
    assert withdrawn.status not in {"CANCELLED", "EXPIRED", "REJECTED", "FILLED"}
    assert withdrawn.report_id is None, "there is no receipt, because nothing was ever submitted"


def test_withdrawing_an_order_that_is_not_pending_is_refused_rather_than_ignored() -> None:
    def factory() -> ActionRule:
        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day == 5:
                return (CancelRequest("fixture:not-a-real-order", "fixture: a stale id", context.snapshot.as_of),)
            return ()

        return decide

    with pytest.raises(ChronologyError, match="withdrawal target is not pending"):
        run(decision_factory=factory)


def test_a_withdrawal_must_be_stamped_at_the_decision_that_issued_it() -> None:
    def factory() -> ActionRule:
        base = buy_and_exit_factory()

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day == 5 and context.pending:
                return (CancelRequest(BUY_A, "fixture: wrong clock", fixture.stamp(2)),)
            return base(context)

        return decide

    with pytest.raises(ChronologyError, match="withdrawal must carry the current decision timestamp"):
        run(decision_factory=factory, scenario=Scenario("delay-one", frozenset(), 1))


def test_a_cancel_request_states_its_own_reason() -> None:
    with pytest.raises(OrderActionError):
        CancelRequest(BUY_A, "", fixture.stamp(5))


# --------------------------------------------------------------------------------------------
# Terminal history: what ended, how much of it traded, and what a retry may ask for.
# --------------------------------------------------------------------------------------------


def test_every_routed_order_reports_how_it_ended_and_where_that_came_from() -> None:
    """A filled order and a receipt-closed order are both terminal, from different evidence."""
    reports = {6: (terminal(SELL_A, 6, status="EXPIRED", filled=0),)}
    result = run(
        decision_factory=lambda: buy_and_exit_factory(limit_cents=200_000),
        execution_provider=execution_with(reports=reports),
    )
    assert result.status == "complete", result.stop_reason
    ended = {record.order_id: record for record in result.terminations}

    assert ended[BUY_A].status == "FILLED"
    assert ended[BUY_A].provenance == "auction"
    assert (ended[BUY_A].filled_qty, ended[BUY_A].residual_qty) == (1000, 0)

    # The exit was priced above the open, so it could not trade; the broker receipt ended it.
    assert ended[SELL_A].status == "EXPIRED"
    assert ended[SELL_A].provenance == "report"
    assert ended[SELL_A].reason == "limit_not_reached"
    assert (ended[SELL_A].filled_qty, ended[SELL_A].residual_qty) == (0, 1000)
    assert ended[SELL_A].report_id == f"expired-{SELL_A}-6"


def test_a_decision_sees_only_the_terminations_that_had_already_happened() -> None:
    seen: list[tuple[int, tuple[str, ...]]] = []

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=200_000)

        def decide(context: DecisionContext) -> Generated:
            seen.append((context.snapshot.as_of.day, tuple(record.order_id for record in context.terminations)))
            return base(context)

        return decide

    run(
        decision_factory=factory,
        execution_provider=execution_with(reports={6: (terminal(SELL_A, 6, status="EXPIRED", filled=0),)}),
    )
    assert seen[0] == (2, ()), "nothing has ended before the first decision"
    assert seen[1] == (5, (BUY_A,)), "the buy filled that morning"
    assert seen[2][1] == (BUY_A, SELL_A)


def test_a_retry_carries_its_parent_and_may_not_exceed_what_was_left() -> None:
    """A partial fill closed by a cancel leaves a residual, and the child is that residual only.

    This covers one child. That a *second* child cannot claim the same residual is a separate
    guarantee with its own test, because the two failed for different reasons.
    """
    child_id = "fixture:7:A:sell:child"
    reports = {6: (terminal(SELL_A, 6, status="CANCELLED", filled=1000),)}
    attempts: list[int] = []

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=90_000, with_signal=True, buy_qty=3000)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None or not parent.residual_qty:
                return ()
            attempts.append(parent.residual_qty)
            order = OrderIntent(child_id, "A", "SELL", parent.residual_qty, 90_000, context.snapshot.as_of)
            return (
                PriorCloseRequest(
                    order,
                    "TWSE",
                    "regular_open",
                    parent.signal,
                    OrderLineage(SELL_A, "residual_retry", parent.available_at),
                ),
            )

        return decide

    result = run(
        initial_cash_cents=600_000_000,
        decision_factory=factory,
        execution_provider=execution_with(allocation={5: 3000, 6: 1000, 8: 2000}, reports=reports),
    )
    assert result.status == "complete", result.stop_reason
    assert attempts == [2000], "3,000 requested, 1,000 filled, so 2,000 is what may be retried"
    sold = [event for event in result.events if event["action"] == "SELL"]
    assert [event["qty"] for event in sold] == [1000, 2000], "cumulative quantity is exact, not doubled"


def test_a_child_may_not_ask_for_more_than_its_parent_left() -> None:
    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=90_000, buy_qty=3000)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None or not parent.residual_qty:
                return ()
            order = OrderIntent("fixture:7:A:sell:greedy", "A", "SELL", 3000, 90_000, context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", None, OrderLineage(SELL_A, "residual_retry", parent.available_at)),)

        return decide

    with pytest.raises(ChronologyError, match="child quantity exceeds the parent residual"):
        run(
            initial_cash_cents=600_000_000,
            decision_factory=factory,
            execution_provider=execution_with(allocation={5: 3000, 6: 1000, 7: 2000}, reports={6: (terminal(SELL_A, 6, status="CANCELLED", filled=1000),)}),
        )


def test_a_child_of_a_live_parent_is_refused_while_its_reservation_is_still_held() -> None:
    """A still-pending order has not released its cash; a second order for it would double the claim."""

    def factory() -> ActionRule:
        base = buy_and_exit_factory()

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day == 5 and any(item.request.intent.order_id == BUY_A for item in context.pending):
                order = OrderIntent("fixture:5:A:buy:child", "A", "BUY", 1000, 110_000, context.snapshot.as_of)
                return (PriorCloseRequest(order, "TWSE", "regular_open", None, OrderLineage(BUY_A, "impatient", context.snapshot.as_of)),)
            return base(context)

        return decide

    with pytest.raises(ChronologyError, match="parent order has not terminated"):
        run(decision_factory=factory, scenario=Scenario("delay-one", frozenset(), 1))


def test_a_terminated_parent_can_be_replaced_once_and_only_once() -> None:
    """Bounding each child against the residual is not enough; the residual must be consumed.

    The earlier version checked `qty <= parent.residual_qty` per child and nothing else, so two
    children -- issued at one decision, or at decisions weeks apart, because a termination record
    never changes -- could each claim the same 2,000 shares. Advice for 3,000 shares then bought
    5,000. A terminated order is now replaceable exactly once; a rule that wants another attempt
    names the child, which has its own residual.
    """
    reports = {6: (terminal(SELL_A, 6, status="CANCELLED", filled=1000),)}

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=90_000, buy_qty=3000)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None or not parent.residual_qty:
                return ()
            lineage = OrderLineage(SELL_A, "residual_retry", parent.available_at)
            return tuple(
                PriorCloseRequest(
                    OrderIntent(f"fixture:7:A:sell:child{index}", "A", "SELL", parent.residual_qty, 90_000, context.snapshot.as_of),
                    "TWSE",
                    "regular_open",
                    parent.signal,
                    lineage,
                )
                for index in (1, 2)
            )

        return decide

    with pytest.raises(ChronologyError, match="parent order has already been replaced"):
        run(
            initial_cash_cents=600_000_000,
            decision_factory=factory,
            execution_provider=execution_with(allocation={5: 3000, 6: 1000, 8: 2000}, reports=reports),
        )


def test_naming_the_same_ancestor_at_a_later_decision_is_refused_too() -> None:
    """The other half of the same guarantee, and the worse one.

    A termination record never expires, so without consuming the residual a rule could come back to
    the original order at every decision for the rest of the run and claim the same shares each
    time. The guard is state on the record, not a per-decision check.
    """
    reports = {6: (terminal(SELL_A, 6, status="CANCELLED", filled=1000),)}
    attempted: list[str] = []

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=90_000, buy_qty=3000)

        def decide(context: DecisionContext) -> Generated:
            day = context.snapshot.as_of.day
            if day not in (7, 8):
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None or not parent.residual_qty:
                return ()
            identity = f"fixture:{day}:A:sell:child"
            attempted.append(identity)
            order = OrderIntent(identity, "A", "SELL", parent.residual_qty, 90_000, context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", parent.signal, OrderLineage(SELL_A, "residual_retry", parent.available_at)),)

        return decide

    with pytest.raises(ChronologyError, match="parent order has already been replaced"):
        run(
            initial_cash_cents=600_000_000,
            decision_factory=factory,
            execution_provider=execution_with(allocation={5: 3000, 6: 1000, 8: 2000, 9: 2000}, reports=reports),
        )
    assert attempted == ["fixture:7:A:sell:child", "fixture:8:A:sell:child"], "the second attempt is a later decision"


def test_an_omitted_replacement_does_not_burn_the_residual_it_never_claimed() -> None:
    """An order that was never queued cannot have taken anything over.

    Recording the parent as replaced by an omitted child would be false twice: the child never
    existed as an order, and the residual would be lost to an arm in which nothing traded. The
    safety property still holds either way, because only a queued order can execute -- so the
    honest choice and the safe choice agree here.
    """
    child_id = "fixture:7:A:sell:child"
    reports = {6: (terminal(SELL_A, 6, status="CANCELLED", filled=1000),)}

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=90_000, buy_qty=3000)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None or not parent.residual_qty:
                return ()
            order = OrderIntent(child_id, "A", "SELL", parent.residual_qty, 90_000, context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", parent.signal, OrderLineage(SELL_A, "residual_retry", parent.available_at)),)

        return decide

    result = run(
        initial_cash_cents=600_000_000,
        decision_factory=factory,
        execution_provider=execution_with(allocation={5: 3000, 6: 1000, 8: 2000}, reports=reports),
        scenario=Scenario("omit-the-retry", frozenset({child_id}), 0, required_omission_ids=frozenset({child_id})),
    )
    assert result.status == "complete", result.stop_reason
    ended = {record.order_id: record for record in result.terminations}
    assert ended[SELL_A].replaced_by is None, "nothing replaced it, so nothing may say it did"
    assert ended[SELL_A].residual_qty == 2000, "the residual is still outstanding"
    assert child_id not in ended, "the child never became an order"
    assert [event["qty"] for event in result.events if event["action"] == "SELL"] == [1000]


def test_a_replacement_is_recorded_on_the_parent_it_replaces() -> None:
    """`replaced_by` is what consumes the residual, so it has to actually be there to read."""
    child_id = "fixture:7:A:sell:child"
    reports = {6: (terminal(SELL_A, 6, status="EXPIRED", filled=0),)}

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=200_000)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None:
                return ()
            order = OrderIntent(child_id, "A", "SELL", parent.residual_qty, 90_000, context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", None, OrderLineage(SELL_A, "residual_retry", parent.available_at)),)

        return decide

    result = run(decision_factory=factory, execution_provider=execution_with(reports=reports))
    assert result.status == "complete", result.stop_reason
    ended = {record.order_id: record for record in result.terminations}
    assert ended[SELL_A].replaced_by == child_id
    assert ended[child_id].parent_order_id == SELL_A


def test_a_receipt_the_lifecycle_never_validated_cannot_describe_an_order() -> None:
    """A report dated past the cutoff is checked against nothing, so it may not be read as fact.

    `_visible_prefix` drops a report whose `event_at` is after the window cutoff and -- unlike a
    report that is merely not yet available -- does not block continuation, so `_validate_reports`
    never sees it. It is not checked against the pending set, nor for cumulative consistency. The
    earlier version read the raw evidence, so such a report could report a filled order as
    `REJECTED` with zero fills, inventing a residual for a replacement to claim.
    """
    ghost = TerminalReport(
        report_id="ghost",
        order_id=BUY_A,
        event_at=fixture.stamp(5, "17:00"),
        available_at=fixture.stamp(5, "17:00"),
        sequence=1,
        status="REJECTED",
        cumulative_filled_qty=0,
        source_id="fixture-broker",
    )
    # `sell_on=0` never matches a fixture day, so the buy is the only order and the ghost receipt
    # is the only thing that could change its recorded fate.
    result = run(
        decision_factory=lambda: buy_and_exit_factory(sell_on=0),
        execution_provider=execution_with(reports={5: (ghost,)}),
    )
    assert result.status == "complete", result.stop_reason
    ended = {record.order_id: record for record in result.terminations}
    assert ended[BUY_A].provenance == "auction", "the auction filled it; an unvalidated receipt cannot say otherwise"
    assert (ended[BUY_A].status, ended[BUY_A].filled_qty, ended[BUY_A].residual_qty) == ("FILLED", 1000, 0)
    assert ended[BUY_A].report_id is None
    assert [event["qty"] for event in result.events if event["action"] == "BUY"] == [1000]


def test_a_child_of_an_unknown_parent_is_refused() -> None:
    def factory() -> ActionRule:
        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 2:
                return ()
            order = OrderIntent(BUY_A, "A", "BUY", 1000, 110_000, context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", None, OrderLineage("fixture:never-existed", "guess", context.snapshot.as_of)),)

        return decide

    with pytest.raises(ChronologyError, match="parent order is unknown"):
        run(decision_factory=factory)


def test_a_child_must_match_its_parents_code_and_side() -> None:
    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=200_000)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None:
                return ()
            order = OrderIntent("fixture:7:B:sell:child", "B", "SELL", 100, 90_000, context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", None, OrderLineage(SELL_A, "wrong_target", parent.available_at)),)

        return decide

    with pytest.raises(ChronologyError, match="child must keep its parent's code and side"):
        run(
            decision_factory=factory,
            execution_provider=execution_with(reports={6: (terminal(SELL_A, 6, status="EXPIRED", filled=0),)}),
        )


# --------------------------------------------------------------------------------------------
# A retry must not be a way around an omission.
# --------------------------------------------------------------------------------------------


def test_a_child_must_carry_the_signal_identity_its_parent_carried() -> None:
    """The load-bearing check: a freshly minted signal would draw its own omission.

    If the child could mint `SELL:A:day-7` while the parent carried `SELL:A`, the sampler would
    roll a new draw for it, and an advice that had been omitted could come back as a retry. So the
    runner requires the child to carry the parent's identity rather than trusting the rule to.
    """

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=200_000, with_signal=True)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None:
                return ()
            order = OrderIntent("fixture:7:A:sell:child", "A", "SELL", 1000, 90_000, context.snapshot.as_of)
            minted = SignalIdentity("SELL:A:retry", "A", "SELL", context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", minted, OrderLineage(SELL_A, "residual_retry", parent.available_at)),)

        return decide

    with pytest.raises(ChronologyError, match="child must carry its parent's signal identity"):
        run(
            decision_factory=factory,
            execution_provider=execution_with(reports={6: (terminal(SELL_A, 6, status="EXPIRED", filled=0),)}),
        )


def test_an_omitted_advice_never_terminates_so_it_cannot_be_retried_at_all() -> None:
    """An omitted request was never queued, so there is no parent for a retry to name."""

    def factory() -> ActionRule:
        base = buy_and_exit_factory(with_signal=True)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day == 5 and "A" in context.snapshot.holdings:
                order = OrderIntent(SELL_A, "A", "SELL", 1000, 90_000, context.snapshot.as_of)
                return (PriorCloseRequest(order, "TWSE", "regular_open", sell_signal(context.snapshot.as_of)),)
            if context.snapshot.as_of.day == 6:
                assert all(record.order_id != SELL_A for record in context.terminations)
                order = OrderIntent("fixture:6:A:sell:child", "A", "SELL", 1000, 90_000, context.snapshot.as_of)
                return (PriorCloseRequest(order, "TWSE", "regular_open", None, OrderLineage(SELL_A, "sneak", context.snapshot.as_of)),)
            return base(context)

        return decide

    with pytest.raises(ChronologyError, match="parent order is unknown"):
        run(decision_factory=factory, scenario=Scenario("omit-the-exit", frozenset({SELL_A}), 0))


def test_a_child_reusing_its_parents_signal_adds_no_second_draw() -> None:
    """One draw per advice, not one per order.

    This is the other half of the omission guarantee. A child of an omitted advice cannot exist --
    the omitted request was never queued, so it never terminated, which the neighbouring test
    pins. What remains to show is that a child of a *kept* advice does not go back to the sampler
    for a fresh answer: it reuses its parent's identity, so the draw table gains no new row and the
    retry can never be luckier than the advice it retries.
    """
    child_id = "fixture:7:A:sell:child"

    def factory() -> ActionRule:
        base = buy_and_exit_factory(limit_cents=200_000, with_signal=True)

        def decide(context: DecisionContext) -> Generated:
            if context.snapshot.as_of.day != 7:
                return base(context)
            parent = next((record for record in context.terminations if record.order_id == SELL_A), None)
            if parent is None:
                return ()
            order = OrderIntent(child_id, "A", "SELL", parent.residual_qty, 90_000, context.snapshot.as_of)
            return (PriorCloseRequest(order, "TWSE", "regular_open", parent.signal, OrderLineage(SELL_A, "residual_retry", parent.available_at)),)

        return decide

    result = run(
        decision_factory=factory,
        execution_provider=execution_with(reports={6: (terminal(SELL_A, 6, status="EXPIRED", filled=0),)}),
        scenario=Scenario("keep-everything", frozenset(), 0, signal_omission=SignalOmission("fixture-seed", Fraction(0))),
    )
    assert result.status == "complete", result.stop_reason
    draws = {draw.signal.signal_id: draw.omitted for draw in result.signal_draws}
    assert draws == {"BUY:A": False, "SELL:A": False}, "three orders, two advices, two draws"
    assert any(event.get("order_id") == child_id for event in result.events), "the retry did execute"
    child = next(record for record in result.terminations if record.order_id == child_id)
    assert child.signal == sell_signal(fixture.stamp(5)), "the child is still the same advice"
    assert child.parent_order_id == SELL_A


# --------------------------------------------------------------------------------------------
# Corporate actions against orders that were fixed before them.
# --------------------------------------------------------------------------------------------


def test_a_split_after_an_order_was_fixed_stops_the_run_when_nothing_says_what_to_do() -> None:
    """The old behaviour submitted the stale order. Refusing is the minimum honest answer."""
    result = run(
        decision_factory=lambda: buy_and_exit_factory(),
        corporate_provider=split_provider(at_day=6, at_time="08:50"),
    )
    assert result.status == "incomplete"
    assert result.stop_reason == "pending_conflicts_corporate_action"
    assert not any(event["action"] == "SELL" for event in result.events), "no sale at a stale size"


def test_a_split_consumed_at_an_earlier_boundary_still_conflicts_at_the_session_it_invalidates() -> None:
    """The conflict is dated against the order, not against the interval that happens to be open.

    The exit is fixed at day 6 and, under a one-session delay, waits for day 8. The split falls on
    day 7 at 14:00 and is consumed by that day's pre-decision corporate call, so by the time day
    8's window asks for corporate evidence there is none left to report. A check scoped to the
    events applied at that window would find nothing and route an order sized for a share count
    that no longer exists.
    """
    result = run(
        frames=frames_with_an_afternoon(),
        decision_factory=lambda: buy_and_exit_factory(sell_on=6),
        corporate_provider=split_provider(at_day=7, at_time="14:00"),
        scenario=Scenario("delay-one", frozenset(), 1),
    )
    assert result.status == "incomplete"
    assert result.stop_reason == "pending_conflicts_corporate_action"


def test_a_split_before_the_order_existed_is_not_a_conflict() -> None:
    """The order was sized after the split, so there is nothing stale about it."""
    result = run(
        frames=frames_with_an_afternoon(),
        decision_factory=lambda: buy_and_exit_factory(sell_on=6),
        execution_provider=execution_with(allocation={7: 2000}),
        corporate_provider=split_provider(at_day=5, at_time="14:00"),
    )
    assert result.status == "complete", result.stop_reason
    sold = [event for event in result.events if event["action"] == "SELL"]
    assert [event["qty"] for event in sold] == [2000], "the exit was sized on the post-split holding"


def notice_only_provider(*, at_day: int, at_time: str, code: str = "A"):
    """A split reported as a notice and nothing else: it moves no position of ours.

    This is the ordinary case for a code we have an order to buy but do not yet hold. The ledger
    correctly records no event -- nothing of ours changed -- so without the notice the runner has
    no way to know the queued order was sized against a share count that no longer exists.
    """
    moment = fixture.stamp(at_day, at_time)

    def provide(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        if not since < moment <= until:
            return CorporateEvidence(f"no-corporate-events-{until.isoformat()}", (), True)
        return CorporateEvidence(
            f"notice-{moment.isoformat()}",
            (),
            True,
            ({"action": "SPLIT", "code": code, "date": moment.isoformat(), "evidence_basis": "fixture: a notice, not an event"},),
        )

    return provide


def test_a_split_on_a_code_we_do_not_hold_yet_still_stales_the_order_to_buy_it() -> None:
    result = run(
        decision_factory=lambda: buy_and_exit_factory(),
        corporate_provider=notice_only_provider(at_day=5, at_time="08:50"),
    )
    assert result.status == "incomplete"
    assert result.stop_reason == "pending_conflicts_corporate_action"
    assert not any(event["action"] == "BUY" for event in result.events)
    # The notice never became a ledger event, so it changed no cash and no position.
    assert all(event["action"] != "SPLIT" for event in result.events)


def test_a_notice_outside_its_own_interval_is_refused() -> None:
    def misdated(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        stale = fixture.stamp(2, "08:50")
        return CorporateEvidence(
            "misdated",
            (),
            True,
            ({"action": "SPLIT", "code": "A", "date": stale.isoformat(), "evidence_basis": "fixture"},),
        )

    with pytest.raises(ChronologyError, match="share-count notices must fall within"):
        run(corporate_provider=misdated)


def test_a_notice_must_name_a_share_count_action() -> None:
    with pytest.raises(ChronologyError, match="share-count notice must name a share-count action"):
        CorporateEvidence(
            "wrong-kind",
            (),
            True,
            ({"action": "DIVIDEND", "code": "A", "date": fixture.stamp(5, "08:50").isoformat()},),
        )


def test_a_policy_may_withdraw_the_stale_order_instead_of_submitting_it() -> None:
    def policy(pending: tuple[PendingRequest, ...], events: Prefix, snapshot: ExecutionAccountSnapshot) -> Sequence[PendingResolution]:
        return [
            PendingResolution(
                item.request.intent.order_id,
                "cancel",
                "corporate_action_changed_the_share_count",
                "fixture: policy chooses to re-decide rather than amend",
            )
            for item in pending
        ]

    result = run(
        decision_factory=lambda: buy_and_exit_factory(),
        corporate_provider=split_provider(at_day=6, at_time="08:50"),
        pending_corporate_policy=policy,
    )
    assert result.status == "complete", result.stop_reason
    assert not any(event["action"] == "SELL" for event in result.events)
    ended = {record.order_id: record for record in result.terminations}
    assert ended[SELL_A].status == "WITHDRAWN"
    assert ended[SELL_A].provenance == "corporate"
    assert ended[SELL_A].reason == "corporate_action_changed_the_share_count"


def test_a_policy_may_amend_and_the_amendment_is_a_traceable_child_not_a_rewrite() -> None:
    """The original order is preserved and terminated; the submitted order is a new identity."""
    child_id = "fixture:5:A:sell:adjusted"

    def policy(pending: tuple[PendingRequest, ...], events: Prefix, snapshot: ExecutionAccountSnapshot) -> Sequence[PendingResolution]:
        held = snapshot.account.positions["A"]
        return [
            PendingResolution(
                item.request.intent.order_id,
                "amend",
                "split_doubled_the_holding",
                "fixture: explicit policy to restate the exit on the new share count",
                replacement_order_id=child_id,
                new_qty=held,
                new_limit_price_cents=45_000,
            )
            for item in pending
        ]

    result = run(
        decision_factory=lambda: buy_and_exit_factory(),
        execution_provider=execution_with(allocation={6: 2000}),
        corporate_provider=split_provider(at_day=6, at_time="08:50"),
        pending_corporate_policy=policy,
    )
    assert result.status == "complete", result.stop_reason
    sold = [event for event in result.events if event["action"] == "SELL"]
    assert [event["qty"] for event in sold] == [2000], "the whole post-split holding, not the stale 1000"
    assert [event["order_id"] for event in sold] == [child_id]

    ended = {record.order_id: record for record in result.terminations}
    assert ended[SELL_A].status == "AMENDED"
    assert ended[SELL_A].provenance == "corporate"
    assert ended[SELL_A].replaced_by == child_id
    assert ended[child_id].parent_order_id == SELL_A
    # The original request is still in the record with its original size.
    original = next(request for record in result.decisions for request in record.requests if request.intent.order_id == SELL_A)
    assert original.intent.qty == 1000


def test_an_amendment_that_is_not_a_board_lot_is_refused_rather_than_floored() -> None:
    """A reverse split can leave a holding that is not a whole number of lots. Say so."""

    def policy(pending: tuple[PendingRequest, ...], events: Prefix, snapshot: ExecutionAccountSnapshot) -> Sequence[PendingResolution]:
        return [
            PendingResolution(
                item.request.intent.order_id,
                "amend",
                "reverse_split_halved_the_holding",
                "fixture: policy tries to sell the exact remaining shares",
                replacement_order_id="fixture:6:A:sell:odd",
                new_qty=snapshot.account.positions["A"],
                new_limit_price_cents=90_000,
            )
            for item in pending
        ]

    def odd_factory() -> ActionRule:
        return buy_and_exit_factory(limit_cents=90_000)

    with pytest.raises(ChronologyError, match="amended quantity is not valid for its venue"):
        run(
            decision_factory=odd_factory,
            execution_provider=execution_with(allocation={5: 1500}),
            corporate_provider=halved_provider(at_day=6, at_time="08:50"),
            pending_corporate_policy=policy,
        )


def test_an_amendment_off_the_tick_grid_is_refused() -> None:
    def policy(pending: tuple[PendingRequest, ...], events: Prefix, snapshot: ExecutionAccountSnapshot) -> Sequence[PendingResolution]:
        return [
            PendingResolution(
                item.request.intent.order_id,
                "amend",
                "split_doubled_the_holding",
                "fixture: a price that no board would accept",
                replacement_order_id="fixture:6:A:sell:offgrid",
                new_qty=snapshot.account.positions["A"],
                new_limit_price_cents=45_001,
            )
            for item in pending
        ]

    with pytest.raises(ChronologyError, match="amended limit price is not on the price grid"):
        run(
            decision_factory=lambda: buy_and_exit_factory(),
            corporate_provider=split_provider(at_day=6, at_time="08:50"),
            pending_corporate_policy=policy,
        )


def test_an_amendment_cannot_sell_more_than_the_holding_the_action_left() -> None:
    def policy(pending: tuple[PendingRequest, ...], events: Prefix, snapshot: ExecutionAccountSnapshot) -> Sequence[PendingResolution]:
        return [
            PendingResolution(
                item.request.intent.order_id,
                "amend",
                "reverse_split_halved_the_holding",
                "fixture: policy ignores the halving",
                replacement_order_id="fixture:6:A:sell:oversold",
                new_qty=1000,
                new_limit_price_cents=90_000,
            )
            for item in pending
        ]

    with pytest.raises(ChronologyError, match="amended quantity exceeds the post-action holding"):
        run(
            decision_factory=lambda: buy_and_exit_factory(),
            corporate_provider=halved_provider(at_day=6, at_time="08:50"),
            pending_corporate_policy=policy,
        )


def test_the_policy_must_answer_for_every_conflicting_order_and_only_those() -> None:
    def silent(pending: tuple[PendingRequest, ...], events: Prefix, snapshot: ExecutionAccountSnapshot) -> Sequence[PendingResolution]:
        return []

    with pytest.raises(ChronologyError, match="policy did not resolve every conflicting order"):
        run(
            decision_factory=lambda: buy_and_exit_factory(),
            corporate_provider=split_provider(at_day=6, at_time="08:50"),
            pending_corporate_policy=silent,
        )

    def extra(pending: tuple[PendingRequest, ...], events: Prefix, snapshot: ExecutionAccountSnapshot) -> Sequence[PendingResolution]:
        return [PendingResolution(item.request.intent.order_id, "cancel", "fine", "fixture") for item in pending] + [
            PendingResolution("fixture:not-conflicting", "cancel", "fine", "fixture")
        ]

    with pytest.raises(ChronologyError, match="policy resolved an order that was not in conflict"):
        run(
            decision_factory=lambda: buy_and_exit_factory(),
            corporate_provider=split_provider(at_day=6, at_time="08:50"),
            pending_corporate_policy=extra,
        )


def test_a_resolution_must_state_a_reason_and_a_basis() -> None:
    with pytest.raises(OrderActionError):
        PendingResolution(SELL_A, "cancel", "", "fixture")
    with pytest.raises(OrderActionError):
        PendingResolution(SELL_A, "cancel", "reason", "")
    with pytest.raises(OrderActionError):
        PendingResolution(SELL_A, "amend", "reason", "fixture")  # no replacement identity or size


# --------------------------------------------------------------------------------------------
# Compatibility: a rule that knows none of this keeps working exactly as before.
# --------------------------------------------------------------------------------------------


def test_a_rule_that_returns_only_requests_behaves_exactly_as_it_did() -> None:
    baseline = harness.run()
    assert baseline.status == "complete"
    assert baseline.snapshots[-1].equity_cents == 209_998_000
    assert baseline.terminations, "terminations are recorded even when nothing reads them"
    assert all(record.parent_order_id is None for record in baseline.terminations)

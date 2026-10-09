"""Stress arms: what an order ID means across arms, and what suppressing an attempt removes.

Two 006 changes, each pinned by the failure it closes:

- `StressInputs` now carries an action rule (withdrawals) and a per-arm corporate policy, and its
  cross-run identity covers a replacement's parent and reason -- including replacements the policy
  creates, which never appear in `decisions`.
- Best-attempt suppression works at the root of each order chain. Through 005 it omitted the BUY
  IDs that filled, so a later target whose entry was a retry could be revived by a rerun that gave
  the retry a different ID, and an entry filled by a corporate amendment made the earliest-request
  lookup raise `StopIteration`.

All prices, allocations and receipts are synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from fractions import Fraction
from typing import Any

import pytest

from research_core.attempt_stress import (
    IDENTITY_FIELDS,
    STATE_DEPENDENT_FIELDS,
    StressInputs,
    request_identity,
    required_roots,
    run_best_attempt_stresses,
)
from research_core.auction import AuctionQuote, OrderIntent
from research_core.chronology import (
    ActionRule,
    ChronologyError,
    CorporateEvidence,
    CorporateProvider,
    DecisionContext,
    ExecutionEvidence,
    ExecutionWindow,
    PendingCorporatePolicy,
    PendingRequest,
    PriorCloseRequest,
    Scenario,
)
from research_core.decision import ExecutionAccountSnapshot
from research_core.order_actions import CancelRequest, OrderLineage, PendingResolution
from research_core.order_lifecycle import TerminalReport
from research_core.signal_stress import run_signal_omission_stresses
from research_core.signals import SignalIdentity, SignalOmission
from scripts.tests import test_research_attempt_stress as attempts
from scripts.tests import test_research_causal_scenarios as fixture
from scripts.tests import test_research_chronology as harness
from scripts.tests import test_research_order_actions as actions
from scripts.tests import test_research_signal_stress as signal_fixture

BUY_A = actions.BUY_A
SELL_A = actions.SELL_A
B_ROOT = "fixture:5:B:buy:1"
CASH = 600_000_000
Prefix = tuple[Mapping[str, Any], ...]


def at(day: int, clock: str = "16:00") -> datetime:
    return fixture.stamp(day, clock)


def order(order_id: str, code: str, side: str, qty: int, limit: int, context: DecisionContext) -> OrderIntent:
    return OrderIntent(order_id, code, side, qty, limit, context.snapshot.as_of)


def request(intent: OrderIntent, lineage: OrderLineage | None = None, signal: SignalIdentity | None = None) -> PriorCloseRequest:
    return PriorCloseRequest(intent, "TWSE", "regular_open", signal, lineage)


def ended(context: DecisionContext, order_id: str):
    return next((record for record in context.terminations if record.order_id == order_id), None)


def market(
    prices: Mapping[int, Mapping[str, int]],
    *,
    allocation: Mapping[tuple[int, str], int] | None = None,
    reports: Mapping[int, tuple[TerminalReport, ...]] | None = None,
):
    """Per-day, per-code prices and allocations; a receipt is handed over only for an order sent that day."""
    allocation = {} if allocation is None else allocation
    reports = {} if reports is None else reports

    def provide(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: tuple[Any, ...]) -> ExecutionEvidence:
        day = window.as_of.day
        sent = {route.order.order_id for route in routes}
        quotes = {
            (route.batch.session_id, route.order.code): AuctionQuote(
                "TRADED",
                prices[day][route.order.code],
                fixture.UNBOUNDED,
                allocation.get((day, route.order.code), 100_000),
                "fixture-open",
                "fixed-test-allocation",
            )
            for route in routes
        }
        return ExecutionEvidence(f"execution-{day}", quotes, tuple(item for item in reports.get(day, ()) if item.order_id in sent), True, True)

    return provide


def stress(
    factory: Callable[[], ActionRule],
    execution: Any,
    *,
    corporate: CorporateProvider | None = None,
    policy_factory: Callable[[], PendingCorporatePolicy] | None = None,
) -> StressInputs:
    return StressInputs(
        CASH,
        5,
        fixture.stamp(2, "00:00"),
        "synthetic-initial",
        harness.frames(),
        "synthetic-complete-calendar",
        True,
        factory,
        lambda: execution,
        lambda: corporate or harness.corporate,
        policy_factory,
    )


FLAT = {day: {"A": 100_000, "B": 100_000} for day in (5, 6, 7, 8)}


# --------------------------------------------------------------------------------------------
# A: identity is lineage-aware; quantity and limit are not identity.
# --------------------------------------------------------------------------------------------


def test_identity_covers_the_parent_and_reason_and_leaves_state_free() -> None:
    signal = SignalIdentity("SELL:A", "A", "SELL", at(5))
    lineage = OrderLineage("parent", "retry", at(6, "13:30"))
    base = PriorCloseRequest(OrderIntent("child", "A", "SELL", 1000, 90_000, at(6)), "TWSE", "regular_open", signal, lineage)
    assert len(request_identity(base)) == len(IDENTITY_FIELDS)
    assert set(IDENTITY_FIELDS).isdisjoint(STATE_DEPENDENT_FIELDS)
    state_changed = replace(
        base,
        intent=replace(base.intent, qty=2000, limit_price_cents=80_000),
        lineage=replace(lineage, known_at=at(6, "14:00")),
    )
    assert request_identity(state_changed) == request_identity(base), "quantity, limit and known_at are the arm's own state"
    assert request_identity(replace(base, lineage=replace(lineage, parent_order_id="another"))) != request_identity(base)
    assert request_identity(replace(base, lineage=replace(lineage, reason="another"))) != request_identity(base)
    assert request_identity(replace(base, lineage=None)) != request_identity(base)


def partial_exit_retry(
    reason_by_call: Callable[[int], str],
    qty_by_call: Callable[[int], int] | None = None,
    limit_by_call: Callable[[int], int] | None = None,
) -> Callable[[], ActionRule]:
    """Sell 3,000, get 1,000, retry the residual at day 6 under a stated reason."""
    calls = 0

    def factory() -> ActionRule:
        nonlocal calls
        calls += 1
        current = calls
        base = actions.buy_and_exit_factory(buy_qty=3000)

        def decide(context: DecisionContext):
            if context.snapshot.as_of.day != 6:
                return base(context)
            parent = ended(context, SELL_A)
            if parent is None or not parent.residual_qty:
                return ()
            qty = parent.residual_qty if qty_by_call is None else qty_by_call(current)
            limit = 90_000 if limit_by_call is None else limit_by_call(current)
            lineage = OrderLineage(SELL_A, reason_by_call(current), parent.available_at)
            return (request(order("fixture:6:A:sell:child", "A", "SELL", qty, limit, context), lineage),)

        return decide

    return factory


def partial_exit_execution():
    reports = {6: (actions.terminal(SELL_A, 6, status="CANCELLED", filled=1000),)}
    return market(FLAT, allocation={(6, "A"): 1000}, reports=reports)


def test_a_reused_child_id_with_a_different_reason_is_refused_in_the_rerun() -> None:
    inputs = stress(partial_exit_retry(lambda call: "residual_retry" if call == 1 else "a_different_reason"), partial_exit_execution())
    baseline = inputs.run(Scenario("baseline", frozenset(), 0))
    assert baseline.status == "complete", baseline.stop_reason
    with pytest.raises(ChronologyError, match="decision identity"):
        inputs.for_rerun(baseline).run(Scenario("rerun", frozenset(), 0))


def test_quantity_and_limit_may_differ_between_arms() -> None:
    """The arm's own residual and price are state, not identity; refusing them would reject an honest rerun."""
    factory = partial_exit_retry(
        lambda call: "residual_retry",
        qty_by_call=lambda call: 2000 if call == 1 else 1000,
        limit_by_call=lambda call: 90_000 if call == 1 else 85_000,
    )
    inputs = stress(factory, partial_exit_execution())
    baseline = inputs.run(Scenario("baseline", frozenset(), 0))
    rerun = inputs.for_rerun(baseline).run(Scenario("rerun", frozenset(), 0))
    assert rerun.status == "complete", rerun.stop_reason
    child = next(item for item in rerun.requests() if item.intent.order_id == "fixture:6:A:sell:child")
    assert (child.intent.qty, child.intent.limit_price_cents) == (1000, 85_000)


def test_an_action_rule_with_withdrawals_passes_the_rerun_check() -> None:
    def factory() -> ActionRule:
        base = actions.buy_and_exit_factory()

        def decide(context: DecisionContext):
            if context.snapshot.as_of.day == 5 and any(item.request.intent.order_id == BUY_A for item in context.pending):
                return (CancelRequest(BUY_A, "fixture: changed its mind", context.snapshot.as_of),)
            return base(context)

        return decide

    inputs = stress(factory, market(FLAT))
    baseline = inputs.run(Scenario("baseline", frozenset(), 0))
    delayed = inputs.for_rerun(baseline).run(Scenario("delay-one", frozenset(), 1))
    assert delayed.status == "complete", delayed.stop_reason
    assert [(record.order_id, record.status) for record in delayed.terminations] == [(BUY_A, "WITHDRAWN")]


def split_notice(code: str, when: datetime):
    record = {"action": "SPLIT", "code": code, "date": when.isoformat(), "ratio_numerator": 2, "ratio_denominator": 1}

    def provide(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        notices = (record,) if since < when <= until else ()
        return CorporateEvidence(f"fixture-{until.isoformat()}", (), True, notices)

    return provide


def amended_entry_factory() -> ActionRule:
    """Buy 1,000 B at day 5 for day 6; sell whatever is held at day 6."""

    def decide(context: DecisionContext):
        day = context.snapshot.as_of.day
        if day == 5:
            return (request(order(B_ROOT, "B", "BUY", 1000, 110_000, context)),)
        if day == 6 and "B" in context.snapshot.holdings:
            return (request(order("fixture:6:B:sell:1", "B", "SELL", context.snapshot.holdings["B"].qty, 40_000, context)),)
        return ()

    return decide


def restating_policy(reason: str = "split_restated"):
    def resolve(conflicts: tuple[PendingRequest, ...], causes: Sequence[Mapping[str, Any]], snapshot: ExecutionAccountSnapshot) -> list[PendingResolution]:
        return [
            PendingResolution(
                item.request.intent.order_id,
                "amend",
                reason,
                "fixture: a 2:1 split restates the entry to twice the shares at half the limit",
                replacement_order_id=f"{item.request.intent.order_id}#restated",
                new_qty=item.request.intent.qty * 2,
                new_limit_price_cents=item.request.intent.limit_price_cents // 2,
            )
            for item in conflicts
        ]

    return resolve


AMEND_PRICES = {5: {"A": 100_000, "B": 100_000}, 6: {"A": 100_000, "B": 50_000}, 7: {"A": 100_000, "B": 60_000}, 8: {"A": 100_000, "B": 60_000}}


def test_a_corporate_amendment_is_traced_and_identity_checked_in_every_arm() -> None:
    calls: list[int] = []

    def policy_factory():
        calls.append(len(calls) + 1)
        return restating_policy("split_restated" if len(calls) == 1 else "a_different_reason")

    inputs = stress(amended_entry_factory, market(AMEND_PRICES), corporate=split_notice("B", at(6, "08:00")), policy_factory=policy_factory)
    baseline = inputs.run(Scenario("baseline", frozenset(), 0))
    assert baseline.status == "complete", baseline.stop_reason
    (amendment,) = baseline.amendments
    assert (amendment.parent_order_id, amendment.request.intent.order_id, amendment.request.intent.qty) == (B_ROOT, f"{B_ROOT}#restated", 2000)
    assert amendment.request.lineage == OrderLineage(B_ROOT, "split_restated", at(6, "08:55"))
    assert f"{B_ROOT}#restated" in {item.intent.order_id for item in baseline.requests()}
    assert f"{B_ROOT}#restated" not in {item.intent.order_id for record in baseline.decisions for item in record.requests}
    with pytest.raises(ChronologyError, match="decision identity"):
        inputs.for_rerun(baseline).run(Scenario("rerun", frozenset(), 0))
    assert calls == [1, 2], "a fresh policy for each arm"


def test_the_same_scenario_twice_gives_the_same_result() -> None:
    inputs = stress(amended_entry_factory, market(AMEND_PRICES), corporate=split_notice("B", at(6, "08:00")), policy_factory=restating_policy)
    first = inputs.run(Scenario("baseline", frozenset(), 0))
    second = inputs.run(Scenario("baseline", frozenset(), 0))
    assert first == second
    assert first.status == "complete"


def test_best_attempt_arms_do_not_depend_on_the_order_they_are_run_in() -> None:
    forward = run_best_attempt_stresses(attempts.inputs(), counts=(1, 2))
    backward = run_best_attempt_stresses(attempts.inputs(), counts=(2, 1))
    assert forward.baseline == backward.baseline
    by_count = {arm.count: arm for arm in forward.arms}
    for arm in backward.arms:
        assert arm == by_count[arm.count]


def test_signal_arms_do_not_depend_on_the_order_they_are_run_in() -> None:
    samplers = (SignalOmission("fixed-a", Fraction(1, 2)), SignalOmission("fixed-b", Fraction(1, 5)))
    forward = run_signal_omission_stresses(signal_fixture.bundled_inputs(), samplers=samplers)
    backward = run_signal_omission_stresses(signal_fixture.bundled_inputs(), samplers=tuple(reversed(samplers)))
    by_sampler = {arm.sampler: arm for arm in forward.arms}
    for arm in backward.arms:
        mine = by_sampler[arm.sampler]
        assert arm.result is not None and mine.result is not None
        assert replace(arm.result, scenario=mine.result.scenario) == mine.result, "only the arm's label may differ"
        assert (arm.omitted_signals, arm.realized_signal_rate, arm.nominal_rate) == (mine.omitted_signals, mine.realized_signal_rate, mine.nominal_rate)


def test_an_id_new_to_the_arms_that_differs_between_them_is_reported_the_same_either_way() -> None:
    def build():
        config = attempts.inputs()
        calls = 0

        def factory() -> ActionRule:
            nonlocal calls
            calls += 1
            current = calls
            original = config.decision_factory()

            def decide(context: DecisionContext):
                snap = context.snapshot
                if current > 1 and snap.as_of.day == 5 and "A" not in snap.holdings:
                    code = "B" if current % 2 else "C"
                    return (PriorCloseRequest(OrderIntent("new-order", code, "BUY", 1000, 30000, snap.as_of), "TWSE", "regular_open"),)
                return tuple(original(context))

            return decide

        frames = tuple(replace(frame, prices={**frame.prices, "B": frame.prices["A"], "C": frame.prices["A"]}) for frame in config.frames)
        return replace(config, decision_factory=factory, frames=frames)

    messages = []
    for counts in ((1, 2), (2, 1)):
        with pytest.raises(ChronologyError, match="cross-run request ID") as caught:
            run_best_attempt_stresses(build(), counts=counts)
        messages.append(str(caught.value))
    assert messages[0] == messages[1] == "cross-run request ID changed its decision identity: new-order"


# --------------------------------------------------------------------------------------------
# B: suppression at the chain root.
# --------------------------------------------------------------------------------------------


def renamed_retry_inputs() -> StressInputs:
    """A: +0 before costs. B: entry is a retry whose ID carries the run number, then +NT$200,000.

    The run number stands for anything that makes a rerun name its retry differently -- in the
    prototype rule, a retry that could not be afforded one day and is issued the next.
    """
    calls = 0

    def factory() -> ActionRule:
        nonlocal calls
        calls += 1
        current = calls

        def decide(context: DecisionContext):
            snap = context.snapshot
            day = snap.as_of.day
            out: list[PriorCloseRequest] = []
            if day == 2:
                out.append(request(order(BUY_A, "A", "BUY", 1000, 110_000, context)))
            if day == 5 and "A" in snap.holdings:
                out.append(request(order(SELL_A, "A", "SELL", 1000, 80_000, context)))
            if day == 5:
                out.append(request(order(B_ROOT, "B", "BUY", 1000, 110_000, context)))
            if day == 6:
                parent = ended(context, B_ROOT)
                if parent is not None and parent.residual_qty and parent.replaced_by is None:
                    lineage = OrderLineage(B_ROOT, "residual_retry", parent.available_at)
                    out.append(request(order(f"{B_ROOT}#retry-run{current}", "B", "BUY", parent.residual_qty, 110_000, context), lineage))
            if day == 7 and "B" in snap.holdings:
                out.append(request(order("fixture:7:B:sell:1", "B", "SELL", snap.holdings["B"].qty, 80_000, context)))
            return tuple(out)

        return decide

    prices = {5: {"A": 100_000, "B": 100_000}, 6: {"A": 100_000, "B": 100_000}, 7: {"A": 100_000, "B": 100_000}, 8: {"A": 100_000, "B": 120_000}}
    reports = {6: (actions.terminal(B_ROOT, 6, status="EXPIRED", filled=0),)}
    return stress(factory, market(prices, allocation={(6, "B"): 0}, reports=reports))


def test_a_later_target_whose_entry_was_a_renamed_retry_is_not_revived() -> None:
    inputs = renamed_retry_inputs()
    result = run_best_attempt_stresses(inputs, counts=(1, 2))
    child = f"{B_ROOT}#retry-run1"
    best_b, best_a = result.ranked_closed_attempts
    assert (best_b.code, best_b.entry_order_id, best_b.buy_order_ids) == ("B", child, frozenset({child}))
    assert (best_b.root_order_ids, best_b.chain_order_ids) == (frozenset({B_ROOT}), frozenset({B_ROOT, child}))
    assert best_b.net_pnl_cents == 20_000_000 - 4000 and best_a.net_pnl_cents == -4000, "1,000 x NT$200, less two NT$20 fees"

    one, two = result.arms
    assert one.result is not None and one.result.status == "complete", one.unavailable_reason
    assert [event["code"] for event in one.result.events] == ["A", "A"], "the other stock's attempt still trades"
    assert two.result is not None and two.result.status == "complete", two.unavailable_reason
    assert two.result.events == (), "neither attempt trades, whatever the rerun names B's retry"
    assert two.result.scenario.required_omission_ids == frozenset({BUY_A}), "the first target root in decision order"
    rows = {row.attempt_id: row for row in two.suppression}
    assert rows[best_b.attempt_id].applied_root_ids == (B_ROOT,)
    assert rows[best_b.attempt_id].descendants_not_regenerated == (child,)
    assert rows[best_b.attempt_id].required_roots_unapplied == ()
    assert rows[best_a.attempt_id].applied_root_ids == (BUY_A,)


def test_the_005_suppression_by_filled_buy_ids_let_that_attempt_trade_again() -> None:
    """The counterexample the root rule exists for, reproduced with 005's omission set."""
    inputs = renamed_retry_inputs()
    baseline = inputs.run(Scenario("baseline", frozenset(), 0))
    old_style = inputs.for_rerun(baseline).run(Scenario("005-style", frozenset({BUY_A, f"{B_ROOT}#retry-run1"}), 0, frozenset({BUY_A})))
    assert old_style.status == "complete", "and nothing marks it as a failed suppression"
    revived = [event for event in old_style.events if event["code"] == "B"]
    assert [event["order_id"] for event in revived] == [f"{B_ROOT}#retry-run2", "fixture:7:B:sell:1"]


def test_an_entry_filled_by_a_corporate_amendment_is_suppressed_at_its_root() -> None:
    inputs = stress(amended_entry_factory, market(AMEND_PRICES), corporate=split_notice("B", at(6, "08:00")), policy_factory=restating_policy)
    result = run_best_attempt_stresses(inputs, counts=(1,))
    (target,) = result.ranked_closed_attempts
    restated = f"{B_ROOT}#restated"
    assert (target.entry_order_id, target.buy_order_ids, target.root_order_ids) == (restated, frozenset({restated}), frozenset({B_ROOT}))
    # 005 searched only decision output for the entry, and the amendment is not decision output.
    with pytest.raises(StopIteration):
        next(item.intent.order_id for record in result.baseline.decisions for item in record.requests if item.intent.order_id in target.buy_order_ids)
    (arm,) = result.arms
    assert arm.result is not None and arm.result.status == "complete", arm.unavailable_reason
    assert arm.result.events == () and arm.result.amendments == ()
    (row,) = arm.suppression
    assert (row.applied_root_ids, row.descendants_not_regenerated) == ((B_ROOT,), (restated,))


def test_a_partially_filled_entry_and_its_retry_are_one_chain() -> None:
    def factory() -> ActionRule:
        def decide(context: DecisionContext):
            snap = context.snapshot
            day = snap.as_of.day
            if day == 2:
                return (request(order(BUY_A, "A", "BUY", 3000, 110_000, context)),)
            parent = ended(context, BUY_A)
            if day == 5 and parent is not None and parent.residual_qty:
                lineage = OrderLineage(BUY_A, "residual_retry", parent.available_at)
                return (request(order(f"{BUY_A}#retry@5", "A", "BUY", parent.residual_qty, 110_000, context), lineage),)
            if day == 6 and "A" in snap.holdings:
                return (request(order("fixture:6:A:sell:1", "A", "SELL", snap.holdings["A"].qty, 80_000, context)),)
            return ()

        return decide

    reports = {5: (actions.terminal(BUY_A, 5, status="CANCELLED", filled=1000),)}
    inputs = stress(factory, market(FLAT, allocation={(5, "A"): 1000}, reports=reports))
    result = run_best_attempt_stresses(inputs, counts=(1,))
    (target,) = result.ranked_closed_attempts
    assert target.buy_order_ids == frozenset({BUY_A, f"{BUY_A}#retry@5"})
    assert target.root_order_ids == frozenset({BUY_A})
    (arm,) = result.arms
    assert arm.result is not None and arm.result.status == "complete" and arm.result.events == ()
    (row,) = arm.suppression
    assert row.descendants_not_regenerated == (f"{BUY_A}#retry@5",)


def shared_root_inputs() -> StressInputs:
    """1,000 of 3,000 fill and are sold; the residual is bought later and becomes a second attempt.

    Both attempts descend from one root, so no omission set can remove one of them without removing
    the other -- which is what makes this the case an exact-one arm has to refuse.
    """

    def factory() -> ActionRule:
        def decide(context: DecisionContext):
            snap = context.snapshot
            day = snap.as_of.day
            if day == 2:
                return (request(order(BUY_A, "A", "BUY", 3000, 110_000, context)),)
            if day == 5 and "A" in snap.holdings:
                return (request(order(SELL_A, "A", "SELL", snap.holdings["A"].qty, 80_000, context)),)
            parent = ended(context, BUY_A)
            if day == 6 and parent is not None and parent.replaced_by is None:
                lineage = OrderLineage(BUY_A, "residual_retry", parent.available_at)
                return (request(order(f"{BUY_A}#retry@6", "A", "BUY", parent.residual_qty, 110_000, context), lineage),)
            if day == 7 and "A" in snap.holdings:
                return (request(order("fixture:7:A:sell:1", "A", "SELL", snap.holdings["A"].qty, 80_000, context)),)
            return ()

        return decide

    prices = {5: {"A": 100_000}, 6: {"A": 100_000}, 7: {"A": 100_000}, 8: {"A": 130_000}}
    reports = {5: (actions.terminal(BUY_A, 5, status="CANCELLED", filled=1000),)}
    return stress(factory, market(prices, allocation={(5, "A"): 1000}, reports=reports))


def test_an_arm_that_cannot_remove_only_what_it_selected_is_refused() -> None:
    """Best-1 over two attempts that share a root: unavailable, not a complete "best one removed".

    006 ran this arm and reported `complete` with no trades at all, calling both attempts one piece
    of advice. That is over-suppression: the second attempt was never selected, and an arm that
    removes it is not the exact-one perturbation it claims to be.
    """
    result = run_best_attempt_stresses(shared_root_inputs(), counts=(1,))
    later, first = result.ranked_closed_attempts
    assert later.entry_order_id == f"{BUY_A}#retry@6" and first.entry_order_id == BUY_A
    assert later.shared_root_attempt_ids == (first.attempt_id,)

    (arm,) = result.arms
    assert arm.result is None, "the arm is not run at all: there is nothing honest to report from it"
    assert arm.unavailable_reason == "nonisolatable_shared_root"
    assert arm.selected_attempt_ids == (later.attempt_id,)
    assert arm.directly_suppressed_attempt_ids == tuple(sorted((first.attempt_id, later.attempt_id)))
    assert arm.suppression == ()


def test_the_same_arm_runs_once_every_attempt_on_that_root_is_selected() -> None:
    """Best-2 selects both, so removing the shared root removes exactly the selected set."""
    result = run_best_attempt_stresses(shared_root_inputs(), counts=(1, 2))
    one, two = result.arms
    assert one.unavailable_reason == "nonisolatable_shared_root" and one.result is None
    assert two.result is not None and two.result.status == "complete", two.unavailable_reason
    assert two.selected_attempt_ids == two.directly_suppressed_attempt_ids
    assert two.result.events == (), "both selected, so the whole chain goes"


def test_an_independent_attempt_in_the_same_stock_does_not_block_isolation() -> None:
    """Two attempts in one code, each from its own root: best-1 is isolatable and runs.

    The point of the refusal above is a shared CHAIN, not a shared ticker. A later, independently
    advised entry in the same stock is a different piece of advice and must stay selectable.
    """

    def factory() -> ActionRule:
        def decide(context: DecisionContext):
            snap = context.snapshot
            day = snap.as_of.day
            if day in (2, 6) and "A" not in snap.holdings:
                return (request(order(f"fixture:{day}:A:buy:1", "A", "BUY", 1000, 110_000, context)),)
            if day in (5, 7) and "A" in snap.holdings:
                return (request(order(f"fixture:{day}:A:sell:1", "A", "SELL", snap.holdings["A"].qty, 80_000, context)),)
            return ()

        return decide

    prices = {5: {"A": 100_000}, 6: {"A": 100_000}, 7: {"A": 100_000}, 8: {"A": 130_000}}
    result = run_best_attempt_stresses(stress(factory, market(prices)), counts=(1,))
    assert len(result.ranked_closed_attempts) == 2
    assert all(target.shared_root_attempt_ids == () for target in result.ranked_closed_attempts)
    (arm,) = result.arms
    assert arm.result is not None and arm.result.status == "complete", arm.unavailable_reason
    assert arm.selected_attempt_ids == arm.directly_suppressed_attempt_ids
    traded = {str(event.get("order_id")) for event in arm.result.events if event.get("order_id")}
    assert not traded & set(arm.targets[0].chain_order_ids), "the selected chain is gone"
    assert traded, "and the other attempt in the same stock still trades"


def test_an_ordinary_independent_root_is_isolatable() -> None:
    """The plain case, so the refusal above cannot be read as refusing everything."""
    result = run_best_attempt_stresses(attempts.inputs(), counts=(1,))
    (arm,) = result.arms
    assert arm.result is not None and arm.result.status == "complete", arm.unavailable_reason
    assert arm.selected_attempt_ids == arm.directly_suppressed_attempt_ids == (arm.targets[0].attempt_id,)


def test_equal_net_pnl_is_ranked_by_entry_order() -> None:
    def factory() -> ActionRule:
        def decide(context: DecisionContext):
            snap = context.snapshot
            day = snap.as_of.day
            if day == 2:
                return (request(order(BUY_A, "A", "BUY", 1000, 110_000, context)),)
            if day == 5 and "A" in snap.holdings:
                return (request(order(SELL_A, "A", "SELL", 1000, 80_000, context)),)
            if day == 6 and "A" not in snap.holdings:
                return (request(order("fixture:6:B:buy:1", "B", "BUY", 1000, 110_000, context)),)
            if day == 7 and "B" in snap.holdings:
                return (request(order("fixture:7:B:sell:1", "B", "SELL", 1000, 80_000, context)),)
            return ()

        return decide

    result = run_best_attempt_stresses(stress(factory, market(FLAT)), counts=(1,))
    first, second = result.ranked_closed_attempts
    assert first.net_pnl_cents == second.net_pnl_cents == -4000
    assert (first.code, second.code) == ("A", "B")
    assert first.attempt_id < second.attempt_id
    assert "not yet paid" in result.ranking_note and "synthetic diagnostic" in result.ranking_note


def test_the_suppression_rows_keep_their_three_non_outcomes_apart() -> None:
    """A later root the rerun never produced is not an unapplied requirement, and is not a descendant."""
    result = run_best_attempt_stresses(attempts.inputs(), counts=(1,))
    (arm,) = result.arms
    (row,) = arm.suppression
    assert row.required_root_ids == ("A-2-BUY",)
    assert row.applied_root_ids == ("A-2-BUY",)
    assert row.roots_not_regenerated == ("A-5-BUY",), "the add was contingent on holding, which the rerun never did"
    assert row.descendants_not_regenerated == ()
    assert row.required_roots_unapplied == ()


def two_entries_one_decision() -> StressInputs:
    """One decision advises A and B; both close. Two target roots at one instant, which is the case
    a rule that only required the chronologically first one could not see."""

    def factory() -> ActionRule:
        def decide(context: DecisionContext):
            snap = context.snapshot
            day = snap.as_of.day
            if day == 2:
                return (
                    request(order(BUY_A, "A", "BUY", 1000, 110_000, context)),
                    request(order("fixture:2:B:buy:1", "B", "BUY", 1000, 110_000, context)),
                )
            if day == 5:
                return tuple(
                    request(order(f"fixture:5:{code}:sell:1", code, "SELL", snap.holdings[code].qty, 80_000, context))
                    for code in ("A", "B")
                    if code in snap.holdings
                )
            return ()

        return decide

    return stress(factory, market(FLAT))


def test_every_root_advised_at_the_first_affected_decision_is_required() -> None:
    """Not just the first of them.

    Omission happens where a request is created, so at that decision the rule has still seen the
    baseline's account: every request it emits there is deterministic. Requiring only one of two
    sibling roots would let a rule that quietly stopped advising the other report a complete --
    but narrower -- suppression.
    """
    result = run_best_attempt_stresses(two_entries_one_decision(), counts=(2,))
    (arm,) = result.arms
    assert arm.result is not None and arm.result.status == "complete", arm.unavailable_reason
    first = next(record for record in result.baseline.decisions if record.requests)
    advised_first = {request.intent.order_id for request in first.requests}
    roots = {root for target in arm.targets for root in target.root_order_ids}
    required = arm.result.scenario.required_omission_ids
    assert roots == {BUY_A, "fixture:2:B:buy:1"}, "both entries were advised at the same decision"
    assert required == frozenset(advised_first & roots)
    # The discriminating assertion: the 005-style "first ID only" rule would give exactly one.
    assert required is not None and len(required) == 2
    assert required_roots(result.baseline, frozenset(roots)) == required
    assert arm.result.events == (), "and both chains really are suppressed"


def test_a_root_advised_at_a_later_decision_is_not_required() -> None:
    """The other half: by then the account has diverged, so the rule may legitimately not advise it."""
    result = run_best_attempt_stresses(renamed_retry_inputs(), counts=(2,))
    (arm,) = result.arms
    assert arm.result is not None and arm.result.status == "complete", arm.unavailable_reason
    required = arm.result.scenario.required_omission_ids
    assert required == frozenset({BUY_A}), "B's root is advised three sessions later"
    assert {root for target in arm.targets for root in target.root_order_ids} == {BUY_A, B_ROOT}


def test_a_required_root_the_rerun_never_produced_is_named_and_incomplete() -> None:
    inputs = attempts.inputs()
    baseline = inputs.run(Scenario("baseline", frozenset(), 0))
    result = inputs.for_rerun(baseline).run(Scenario("typo", frozenset({"A-3-BUY"}), 0, frozenset({"A-3-BUY"})))
    assert result.stop_reason == "unapplied_omission_targets"
    assert result.unmatched_omission_ids == frozenset({"A-3-BUY"})

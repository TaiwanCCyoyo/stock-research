"""Chronological reruns with fixed synthetic prices; no market strategy verdict."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from research_core.auction import AuctionBatch, AuctionQuote, OrderIntent, RoutedOrder
from research_core.chronology import (
    ChronologyError,
    ChronologyResult,
    CorporateEvidence,
    DayFrame,
    DecisionContext,
    DecisionRule,
    ExecutionEvidence,
    ExecutionWindow,
    PriorCloseRequest,
    Scenario,
    SessionRoute,
    run_chronology,
)
from research_core.decision import CloseObservation, ExecutionAccountSnapshot
from research_core.order_actions import CancelRequest
from research_core.order_lifecycle import TerminalReport
from scripts.tests import test_research_causal_scenarios as fixture
from scripts.tests import test_research_cohort_lifecycle as cohort_fixture

Prefix = tuple[Mapping[str, Any], ...]
Requests = tuple[PriorCloseRequest, ...]
Routes = tuple[RoutedOrder, ...]


def frames() -> tuple[DayFrame, ...]:
    result = []
    for index, day in enumerate(fixture.DAYS):
        windows: tuple[ExecutionWindow, ...] = ()
        if index:
            batch = AuctionBatch("TWSE", "regular_open", fixture.stamp(day, "08:55"), fixture.stamp(day, "09:00"), f"synthetic-{day}")
            windows = (ExecutionWindow(f"window-{day}", (SessionRoute(batch, fixture.COSTS),), fixture.stamp(day, "13:30"), fixture.stamp(day)),)
        observations = {
            code: CloseObservation(raw, Decimal(raw) / 200, fixture.stamp(day, "13:30"), fixture.stamp(day, "15:00"), "fixture-close")
            for code, raw in fixture.RAW_CLOSE[day].items()
        }
        result.append(DayFrame(date(2026, 1, day), fixture.stamp(day, "13:30"), fixture.stamp(day), observations, windows))
    return tuple(result)


def advised(actions: Sequence[PriorCloseRequest | CancelRequest]) -> Requests:
    """Narrow an action rule's output to the requests these fixtures advise.

    The shared runner takes withdrawals as well as requests; every fixture that uses this helper
    advises orders only, so a `CancelRequest` arriving here is a fixture bug, not a case to handle.
    """
    for action in actions:
        if not isinstance(action, PriorCloseRequest):
            raise AssertionError(f"fixture rule produced {type(action).__name__}")
    return cast(Requests, tuple(actions))


def factory() -> DecisionRule:
    def decide(context: DecisionContext) -> Requests:
        snap = context.snapshot
        return tuple(PriorCloseRequest(order, "TWSE", "regular_open") for order in fixture.recommendations(snap, fixture.RANKED_CANDIDATE.get(snap.as_of.day)))

    return decide


def execution(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Routes) -> ExecutionEvidence:
    day = window.as_of.day
    quotes = {
        (route.batch.session_id, code): AuctionQuote("TRADED", price, fixture.UNBOUNDED, 1000, "fixture-open", "fixed-test-allocation")
        for route in routes
        for code, price in fixture.OPEN[day].items()
    }
    return ExecutionEvidence(f"execution-{day}", quotes, (), True, True)


def corporate(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
    return CorporateEvidence(f"no-corporate-events-{until.isoformat()}", (), True)


def run(**overrides: Any) -> ChronologyResult:
    args: dict[str, Any] = {
        "initial_cash_cents": fixture.INITIAL_CENTS,
        "max_positions": 5,
        "history_start": fixture.stamp(2, "00:00"),
        "initial_checkpoint_id": "synthetic-initial-cash-only",
        "frames": frames(),
        "calendar_id": "synthetic-complete-calendar",
        "calendar_complete": True,
        "scenario": Scenario("baseline", frozenset(), 0),
        "decision_factory": factory,
        "execution_provider": execution,
        "corporate_provider": corporate,
    }
    args.update(overrides)
    return run_chronology(**args)


def test_runner_reproduces_hand_calculated_baseline_omission_and_delay_paths() -> None:
    baseline = run()
    omitted = run(scenario=Scenario("omit-first-a", frozenset({fixture.identity(2, "A")}), 0))
    delayed = run(scenario=Scenario("extra-day", frozenset(), 1))
    assert baseline.status == omitted.status == delayed.status == "complete"
    assert baseline.snapshots[-1].equity_cents == 209_998_000
    assert omitted.snapshots[-1].equity_cents == 224_996_000
    assert delayed.snapshots[-1].equity_cents == 219_998_000
    assert [event["order_id"] for event in baseline.events] == [fixture.identity(2, "A")]
    assert [event["order_id"] for event in omitted.events] == [fixture.identity(5, "B"), fixture.identity(6, "A")]
    assert delayed.events[0]["date"] == fixture.stamp(6, "09:00").isoformat()
    assert delayed.events[0]["price"] == 900
    last = delayed.windows[-1].result
    assert last is not None and last.initial_result.outcomes[0].reason == "insufficient_reserved_cash"


def test_scenario_names_do_not_leak_into_decision_or_execution_context() -> None:
    decisions: list[DecisionContext] = []
    accounts: list[ExecutionAccountSnapshot] = []

    def probing_factory() -> DecisionRule:
        original = factory()

        def decide(context: DecisionContext) -> Requests:
            decisions.append(context)
            if "special-scenario" in context.snapshot.execution_checkpoint_id:
                return ()
            return tuple(original(context))

        return decide

    def probing_execution(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Routes) -> ExecutionEvidence:
        accounts.append(snapshot)
        return execution(window, snapshot, routes)

    baseline = run(decision_factory=probing_factory, execution_provider=probing_execution)
    baseline_decisions, baseline_accounts = tuple(decisions), tuple(accounts)
    decisions.clear()
    accounts.clear()
    renamed = run(
        scenario=Scenario("special-scenario", frozenset(), 0),
        decision_factory=probing_factory,
        execution_provider=probing_execution,
    )
    assert baseline.status == renamed.status == "complete"
    assert baseline.events == renamed.events
    assert baseline_decisions == tuple(decisions)
    assert baseline_accounts == tuple(accounts)
    assert baseline_accounts


def test_delay_beyond_horizon_retains_requests_and_is_not_a_completed_run() -> None:
    result = run(scenario=Scenario("three-extra-days", frozenset(), 3))
    assert result.status == "incomplete" and result.stop_reason == "outstanding_requests"
    assert [pending.request.intent.order_id for pending in result.pending] == [fixture.identity(5, "B"), fixture.identity(6, "A")]
    assert result.events[0]["date"] == fixture.stamp(8, "09:00").isoformat()


def test_missing_execution_stops_before_new_close_or_decision() -> None:
    calls: list[str] = []

    def missing(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Routes) -> ExecutionEvidence:
        calls.append(window.window_id)
        return ExecutionEvidence("missing", {}, (), True, True)

    result = run(execution_provider=missing)
    assert result.status == "incomplete"
    assert len(result.snapshots) == 1 and result.events == ()
    assert calls == ["window-5"]
    diagnostic = result.windows[0].result
    assert diagnostic is not None and diagnostic.next_state is None


@pytest.mark.parametrize("complete,exclusive", [(False, True), (True, False)])
def test_incomplete_or_nonexclusive_provider_cannot_certify_a_book(complete: bool, exclusive: bool) -> None:
    def bad(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Routes) -> ExecutionEvidence:
        return replace(execution(window, snapshot, routes), complete=complete, exclusive=exclusive)

    result = run(execution_provider=bad)
    assert result.status == "incomplete" and len(result.snapshots) == 1
    assert result.events == ()


def test_unknown_corporate_interval_is_not_replaced_by_zero_events() -> None:
    result = run(corporate_provider=lambda since, until, prefix: CorporateEvidence("unknown", (), False))
    assert result.status == "incomplete" and result.snapshots == ()


def test_missing_due_session_is_not_silently_postponed_to_a_later_open() -> None:
    altered = list(frames())
    altered[1] = replace(altered[1], windows=())
    with pytest.raises(ChronologyError, match="missing_due_session"):
        run(frames=altered)


def test_corporate_provider_recomputes_from_each_scenarios_executed_prefix() -> None:
    def with_dividend(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        when = fixture.stamp(6, "08:00")
        events: Prefix = ()
        if since < when <= until and any(event["code"] == "A" and event["action"] == "BUY" for event in prefix):
            events = (
                {
                    "action": "DIVIDEND_ENTITLEMENT",
                    "code": "A",
                    "date": when.isoformat(),
                    "total": 0,
                    "amount": 10000,
                    "entitlement_id": "synthetic-distribution",
                },
                {"action": "DIVIDEND", "code": "A", "date": when.isoformat(), "total": 10000, "entitlement_id": "synthetic-distribution"},
            )
        return CorporateEvidence("synthetic-corporate-rule", events, True)

    baseline = run(corporate_provider=with_dividend)
    omitted = run(corporate_provider=with_dividend, scenario=Scenario("omit", frozenset({fixture.identity(2, "A")}), 0))
    assert sum(event["action"] == "DIVIDEND" for event in baseline.events) == 1
    assert not any(event["action"] == "DIVIDEND" for event in omitted.events)
    assert baseline.snapshots[-1].equity_cents == 210_998_000


def test_fresh_decision_factory_and_visible_queue_avoid_shared_strategy_state() -> None:
    created: list[object] = []
    queues: list[tuple[str, ...]] = []

    def fresh() -> DecisionRule:
        created.append(object())
        base = factory()

        def decide(context: DecisionContext) -> Sequence[PriorCloseRequest]:
            queues.append(tuple(pending.request.intent.order_id for pending in context.pending))
            return base(context)

        return decide

    first = run(decision_factory=fresh, scenario=Scenario("delay", frozenset(), 1))
    second = run(decision_factory=fresh, scenario=Scenario("delay", frozenset(), 1))
    assert len(created) == 2
    assert first.events == second.events
    assert (fixture.identity(2, "A"),) in queues


def test_bad_calendar_and_future_decision_cannot_be_treated_as_a_failed_candidate() -> None:
    with pytest.raises(ChronologyError):
        run(calendar_complete=False)
    with pytest.raises(ChronologyError):
        run(frames=tuple(reversed(frames())))

    def future() -> DecisionRule:
        def decide(context: DecisionContext) -> Requests:
            intent = OrderIntent("future", "A", "BUY", 1000, 100000, fixture.stamp(8))
            return (PriorCloseRequest(intent, "TWSE", "regular_open"),)

        return decide

    with pytest.raises(ChronologyError):
        run(decision_factory=future)


def test_missing_held_mark_stops_without_an_invented_zero_value() -> None:
    altered = list(frames())
    altered[2] = replace(altered[2], prices={"B": altered[2].prices["B"]})
    result = run(frames=altered)
    assert result.status == "incomplete" and result.stop_reason == "missing_close_marks"
    assert len(result.snapshots) == len(result.decisions) == 2
    assert len(result.events) == 1


def test_payment_after_lifecycle_is_added_only_after_immediate_execution_reconciliation() -> None:
    altered = list(frames())
    altered[1] = replace(altered[1], windows=(replace(altered[1].windows[0], as_of=fixture.stamp(5, "13:30")),))

    def later_payment(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        when = fixture.stamp(5, "15:30")
        events: Prefix = ()
        if since < when <= until:
            events = (
                {"action": "DIVIDEND_ENTITLEMENT", "code": "A", "date": when.isoformat(), "amount": 10000, "total": 0, "entitlement_id": "later"},
                {"action": "DIVIDEND", "code": "A", "date": when.isoformat(), "total": 10000, "entitlement_id": "later"},
            )
        return CorporateEvidence("post-lifecycle-payment", events, True)

    result = run(frames=altered, corporate_provider=later_payment)
    assert result.status == "complete"
    lifecycle = result.windows[0].result
    assert lifecycle is not None and lifecycle.next_state is not None
    assert lifecycle.next_state.cash_cents == 99_998_000
    assert result.snapshots[1].cash_cents == 100_998_000
    assert result.snapshots[-1].equity_cents == 210_998_000


@pytest.mark.parametrize("action", ["BUY", "SPLIT"])
def test_corporate_provider_cannot_inject_fills_or_cross_the_consumed_interval(action: str) -> None:
    def invalid(since: datetime, until: datetime, prefix: Prefix) -> CorporateEvidence:
        return CorporateEvidence("invalid", ({"action": action, "date": since.isoformat(), "code": "A", "qty": 1000, "total": -100},), True)

    with pytest.raises(ChronologyError):
        run(corporate_provider=invalid)


def test_queue_aware_rule_can_avoid_duplicate_unsubmitted_entries_under_delay() -> None:
    def aware_factory() -> DecisionRule:
        base = factory()

        def decide(context: DecisionContext) -> Requests:
            waiting = {pending.request.intent.code for pending in context.pending}
            return tuple(request for request in base(context) if request.intent.code not in waiting)

        return decide

    result = run(decision_factory=aware_factory, scenario=Scenario("delay-three", frozenset(), 3))
    assert result.status == "incomplete"
    assert [item.request.intent.order_id for item in result.pending] == [fixture.identity(5, "B")]
    assert not any(request.intent.order_id == fixture.identity(6, "A") for decision in result.decisions for request in decision.requests)


def multi_session_case(*, unresolved: bool = False) -> ChronologyResult:
    prepared = list(frames()[:2])
    regular = ExecutionWindow(
        "regular",
        (SessionRoute(cohort_fixture.TWSE, fixture.COSTS), SessionRoute(cohort_fixture.TPEX, cohort_fixture.OTHER_COSTS)),
        cohort_fixture.t("13:30"),
        cohort_fixture.t("09:04"),
    )
    odd_batch = AuctionBatch("TWSE", "intraday_odd", cohort_fixture.t("09:05"), cohort_fixture.t("09:10"), "odd-session")
    odd = ExecutionWindow("odd", (SessionRoute(odd_batch, fixture.COSTS),), cohort_fixture.t("13:30"), cohort_fixture.t("13:30"))
    for index, raw in enumerate(({"A": 10000, "B": 20000}, {"A": 10300, "B": 20200})):
        frame = prepared[index]
        prices = {code: CloseObservation(value, Decimal(value) / 200, frame.close_at, frame.decision_at, "multi-close") for code, value in raw.items()}
        prepared[index] = replace(frame, prices=prices, windows=() if index == 0 else (regular, odd))

    def both() -> DecisionRule:
        def decide(context: DecisionContext) -> Requests:
            if context.snapshot.as_of.day != 2:
                return ()
            requests = tuple(PriorCloseRequest(route.order, route.batch.exchange, route.batch.venue) for route in cohort_fixture.ROUTES)
            child = OrderIntent("a-odd", "A", "BUY", 250, 11000, context.snapshot.as_of)
            return (*requests, PriorCloseRequest(child, "TWSE", "intraday_odd"))

        return decide

    def supplied(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Routes) -> ExecutionEvidence:
        if window.window_id == "regular":
            reports = cohort_fixture.reports()
            return ExecutionEvidence("regular-evidence", cohort_fixture.QUOTES, tuple(reports[:-1] if unresolved else reports), True, True)
        return ExecutionEvidence(
            "odd-evidence", {(odd_batch.session_id, "A"): AuctionQuote("TRADED", 10200, cohort_fixture.LIMIT_A, 250, "odd", "fixed")}, (), True, True
        )

    return run(frames=prepared, decision_factory=both, execution_provider=supplied)


def test_runner_connects_cross_market_residuals_later_odd_venue_and_close() -> None:
    result = multi_session_case()
    assert result.status == "complete" and len(result.windows) == 2
    assert result.snapshots[-1].cash_cents == 157_343_000
    assert result.snapshots[-1].equity_cents == 200_718_000
    assert result.events[-1]["date"] == cohort_fixture.t("09:10").isoformat()
    assert result.events[-1]["price"] == 102


def test_unresolved_first_cohort_prevents_odd_venue_and_preserves_diagnostics_separately() -> None:
    result = multi_session_case(unresolved=True)
    assert result.status == "incomplete" and result.stop_reason == "execution_unresolved"
    assert len(result.windows) == len(result.snapshots) == 1
    assert result.events == ()
    diagnostic = result.windows[0].result
    assert diagnostic is not None and len(diagnostic.initial_result.ledger_events) == 2 and len(diagnostic.additional_events) == 1
    assert [item.request.intent.order_id for item in result.pending] == ["a-odd"]


def test_overlapping_exclusive_windows_are_invalid_even_if_a_fixture_has_no_due_orders() -> None:
    prepared = list(frames())
    frame = prepared[1]
    later = AuctionBatch("TWSE", "intraday_odd", fixture.stamp(5, "09:05"), fixture.stamp(5, "09:10"), "overlap")
    window = ExecutionWindow("overlap", (SessionRoute(later, fixture.COSTS),), fixture.stamp(5, "13:30"), fixture.stamp(5))
    prepared[1] = replace(frame, windows=(*frame.windows, window))
    with pytest.raises(ChronologyError, match="overlap"):
        run(frames=prepared)


def test_reused_report_id_in_a_later_window_does_not_look_like_fresh_evidence() -> None:
    def cancel(window: ExecutionWindow, snapshot: ExecutionAccountSnapshot, routes: Routes) -> ExecutionEvidence:
        report = TerminalReport("reused", routes[0].order.order_id, window.sessions[0].batch.auction_at, window.as_of, 1, "CANCELLED", 0, "fixture-terminal")
        quotes = {(route.batch.session_id, route.order.code): AuctionQuote("NO_TRADE", None, None, None, "fixture-no-trade") for route in routes}
        return ExecutionEvidence("source-reused-legitimately", quotes, (report,), True, True)

    with pytest.raises(ChronologyError, match="report IDs"):
        run(execution_provider=cancel)


def test_unapplied_omission_target_is_not_certified_as_a_completed_perturbation() -> None:
    baseline = run()
    typo = run(scenario=Scenario("typo", frozenset({"never-generated"}), 0))
    assert typo.events == baseline.events
    assert typo.status == "incomplete" and typo.stop_reason == "unapplied_omission_targets"
    assert typo.matched_omission_ids == frozenset()
    assert typo.unmatched_omission_ids == frozenset({"never-generated"})
    requested = frozenset({fixture.identity(2, "A"), "never-generated"})
    partial = run(scenario=Scenario("partial-targets", requested, 0))
    assert partial.status == "incomplete"
    assert partial.matched_omission_ids == frozenset({fixture.identity(2, "A")})
    assert partial.unmatched_omission_ids == frozenset({"never-generated"})
    early = run(scenario=Scenario("unknown", requested, 0), corporate_provider=lambda since, until, prefix: CorporateEvidence("unknown", (), False))
    assert early.stop_reason == "corporate_evidence_incomplete"  # Keep the first real stop reason.

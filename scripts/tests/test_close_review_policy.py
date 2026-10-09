"""Synthetic close advice and next-session chronology; no market artifacts."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from research_core.auction import AuctionBatch, AuctionQuote, CostSchedule, buy_quantity_for_budget
from research_core.chronology import (
    CorporateEvidence,
    DayFrame,
    DecisionContext,
    ExecutionEvidence,
    ExecutionWindow,
    PendingRequest,
    Scenario,
    SessionRoute,
    run_chronology,
)
from research_core.decision import CloseObservation, DecisionSnapshot, HeldAttempt
from research_core.execution_prices import PriceLimits
from research_core.order_lifecycle import TerminalReport

LOCATION = Path(__file__).resolve().parents[2] / "tasks" / "20261005-relative-strength-holding" / "policy.py"
SPEC = importlib.util.spec_from_file_location("close_review_policy_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
policy_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = policy_module
SPEC.loader.exec_module(policy_module)
CloseReviewPolicy = policy_module.CloseReviewPolicy
PolicyFeature = policy_module.PolicyFeature
PolicyError = policy_module.PolicyError
COSTS = CostSchedule(Fraction(1, 100), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
BOUNDS = PriceLimits(Decimal("0.01"), None)  # Explicit synthetic bounds only.


def stamp(day: int = 2, clock: str = "16:00") -> datetime:
    return datetime.fromisoformat(f"2026-01-{day:02d}T{clock}:00+08:00")


def feature(day: int = 2, **changes: Any) -> Any:
    return PolicyFeature(**{
        "exchange": "TWSE",
        "available_at": stamp(day, "15:00"),
        "source_id": "synthetic-feature",
        "eligible": True,
        "rs60": Decimal("0.8"),
        "ret60": Decimal("0.1"),
        "ma20": Decimal("90"),
        "ma60": Decimal("80"),
        **changes,
    })


def price(day: int = 2, raw: int = 10_000, signal: str = "100") -> CloseObservation:
    return CloseObservation(raw, Decimal(signal), stamp(day, "13:30"), stamp(day, "15:00"), "synthetic-close")


def snapshot(
    *,
    day: int = 2,
    codes: tuple[str, ...] = ("A",),
    cash: int = 200_000_000,
    holdings: dict[str, HeldAttempt] | None = None,
    claims: frozenset[str] = frozenset(),
) -> DecisionSnapshot:
    return DecisionSnapshot(
        as_of=stamp(day),
        calendar_id="synthetic-calendar",
        event_count=0,
        cash_cents=cash,
        receivable_cents=0,
        equity_cents=cash,
        cash_basis="trade_date_cash",
        execution_checkpoint_id="synthetic-checkpoint",
        evidence_basis="synthetic",
        holdings=holdings or {},
        prices={code: price(day) for code in codes},
        occupied_issuer_codes=claims,
    )


def policy(features: dict[str, Any], *, days: int = 20, absent: frozenset[date] = frozenset()) -> Any:
    return CloseReviewPolicy(exit_ma_days=days, feature_provider=lambda as_of: features, costs=COSTS, absent_dates=absent)


def held(*, qty: int = 1000, age: int = 1) -> HeldAttempt:
    return HeldAttempt(0, qty, stamp(2, "09:00"), age)


def test_rank_threshold_ties_order_and_cost_inclusive_whole_lot_budget() -> None:
    features = {
        "A": feature(rs60=Decimal("0.8")),
        "B": feature(rs60=Decimal("0.799999")),
        "C": feature(rs60=Decimal("0.9"), ret60=Decimal("0.2")),
        "D": feature(rs60=Decimal("0.9"), ret60=Decimal("0.2")),
        "E": feature(rs60=Decimal("0.9"), ret60=Decimal("0.3")),
    }
    rule = policy(features)
    requests = rule(DecisionContext(snapshot(codes=tuple(features)), ()))
    assert [item.intent.code for item in requests] == ["E", "C", "D", "A"]
    assert all(item.intent.limit_price_cents == 10_200 for item in requests)
    assert all(item.intent.qty == 3000 for item in requests)
    assert requests[0].intent.qty == buy_quantity_for_budget(budget_cents=40_000_000, price_cents=10_200, costs=COSTS, venue="regular_open")
    assert all(item.venue == "regular_open" and item.signal.origin_at == stamp() for item in requests)
    assert rule.reviews[-1].skipped[0].reason == "rs60_below_threshold"
    assert all(item.reserved_budget_cents == 40_000_000 for item in rule.reviews[-1].requests)


def test_cash_reserves_do_not_reallocate_lot_spare_and_zero_lot_skips_next() -> None:
    features = {code: feature() for code in ("A", "B", "C")}
    rule = policy(features)
    requests = rule(DecisionContext(snapshot(codes=tuple(features), cash=40_000_000), ()))
    assert [item.intent.code for item in requests] == ["A"]
    assert requests[0].intent.qty * 10_200 < 40_000_000  # spare deliberately not reused
    assert {item.reason for item in rule.reviews[-1].skipped} == {"budget_cannot_fund_cost_inclusive_lot"}
    snap = snapshot(codes=("A", "B"), cash=2_000_000)
    snap = replace(snap, prices={"A": price(), "B": price(raw=1000, signal="100")})
    rule = policy({"A": feature(), "B": feature()})
    requests = rule(DecisionContext(snap, ()))
    assert [item.intent.code for item in requests] == ["B"]
    assert rule.reviews[-1].requests[0].reserved_budget_cents == 2_000_000


def test_five_slots_claim_slots_no_add_and_no_preborrow_of_exit_proceeds() -> None:
    codes = tuple("ABCDEF")
    features = {code: feature() for code in codes}
    requests = policy(features)(DecisionContext(snapshot(codes=codes, cash=400_000_000), ()))
    assert [item.intent.code for item in requests] == list("ABCDE")
    requests = policy(features)(DecisionContext(snapshot(codes=codes, claims=frozenset("WXYZ")), ()))
    assert [item.intent.code for item in requests] == ["A"]
    exiting_features = {code: feature(ma20=Decimal("110")) if code in "ABCDE" else feature() for code in codes}
    snap = snapshot(codes=codes, cash=0, holdings={code: held() for code in "ABCDE"})
    requests = policy(exiting_features)(DecisionContext(snap, ()))
    assert [item.intent.side for item in requests] == ["SELL"] * 5
    assert [item.intent.code for item in requests] == list("ABCDE")
    # Even positive existing cash cannot release the fifth slot before a sell fill.
    requests = policy(exiting_features)(DecisionContext(replace(snap, cash_cents=40_000_000), ()))
    assert all(item.intent.side == "SELL" for item in requests)
    snap = snapshot(holdings={"A": held()}, cash=200_000_000)
    assert policy({"A": feature()})(DecisionContext(snap, ())) == ()


def test_twenty_vs_sixty_exit_age_limit_signal_price_and_raw_limit() -> None:
    snap = snapshot(holdings={"A": held()})
    features = {"A": feature(ma20=Decimal("110"), ma60=Decimal("90"))}
    requests = policy(features, days=20)(DecisionContext(snap, ()))
    assert len(requests) == 1 and requests[0].intent.side == "SELL"
    assert requests[0].intent.qty == 1000 and requests[0].intent.limit_price_cents == 9000
    assert policy(features, days=60)(DecisionContext(snap, ())) == ()
    snap = replace(snap, holdings={"A": held(age=252)})
    for days in (20, 60):
        rule = policy({"A": feature()}, days=days)
        assert rule(DecisionContext(snap, ()))[0].intent.side == "SELL"
        assert rule.reviews[-1].requests[0].reason == "max_completed_closes"
    snap = snapshot()
    snap = replace(snap, prices={"A": price(raw=10_000, signal="12")})
    assert policy({"A": feature(ma20=Decimal("11"))})(DecisionContext(snap, ()))[0].intent.limit_price_cents == 10_200
    assert policy({"A": feature(ma20=Decimal("12"))})(DecisionContext(snap, ())) == ()


def test_tick_rounding_directions_are_fixed_advice_not_exchange_bounds() -> None:
    snap = replace(snapshot(), prices={"A": price(raw=4995)})
    request = policy({"A": feature()})(DecisionContext(snap, ()))[0]
    assert request.intent.limit_price_cents == 5090  # 49.95*1.02=50.949, round DOWN
    snap = replace(snap, holdings={"A": held()})
    request = policy({"A": feature(ma20=Decimal("110"))})(DecisionContext(snap, ()))[0]
    assert request.intent.limit_price_cents == 4500  # 49.95*.90=44.955, round UP


def test_unfilled_re_evaluation_uses_new_features_and_new_signal_identity() -> None:
    records = {"A": feature()}
    rule = policy(records)
    first = rule(DecisionContext(snapshot(), ()))[0]
    records["A"] = feature(5, rs60=Decimal("0.7"))
    assert rule(DecisionContext(snapshot(day=5), ())) == ()
    records["A"] = feature(6)
    latest = rule(DecisionContext(snapshot(day=6), ()))[0]
    assert latest.intent.order_id != first.intent.order_id
    assert latest.signal.signal_id != first.signal.signal_id
    assert latest.signal.origin_at == stamp(6)
    assert len(rule.reviews) == 3


def test_absence_never_replays_buy_or_exit_and_resume_can_hold_recovery() -> None:
    calls = []

    def provider(as_of: datetime) -> dict[str, Any]:
        calls.append(as_of)
        return {"A": feature(as_of.day, rs60=Decimal("0.7") if as_of.day == 6 else Decimal("0.9"))}

    rule = CloseReviewPolicy(exit_ma_days=20, feature_provider=provider, costs=COSTS, absent_dates=frozenset({date(2026, 1, 5)}))
    assert len(rule(DecisionContext(snapshot(), ()))) == 1
    assert rule(DecisionContext(snapshot(day=5), ())) == ()
    assert rule.reviews[-1].absent
    assert rule(DecisionContext(snapshot(day=6), ())) == ()
    assert calls == [stamp(2), stamp(6)]
    snap = snapshot(day=5, holdings={"A": held()})
    snap = replace(snap, prices={"A": price(5, signal="50")})
    assert rule(DecisionContext(snap, ())) == ()
    recovered = snapshot(day=6, holdings={"A": held(age=3)})
    assert rule(DecisionContext(recovered, ())) == ()


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"eligible": 1}, "eligible"),
        ({"rs60": 0.8}, "Decimal"),
        ({"rs60": Decimal("NaN")}, "finite"),
        ({"ret60": Decimal("Infinity")}, "finite"),
        ({"rs60": Decimal("1.01")}, "within"),
        ({"rs60": Decimal("-0.01")}, "within"),
        ({"ma20": Decimal(0)}, "positive"),
        ({"ma60": Decimal(-1)}, "positive"),
        ({"exchange": "UNKNOWN"}, "exchange"),
        ({"source_id": " "}, "source_id"),
        ({"available_at": datetime(2026, 1, 2, 15)}, "timestamp"),
    ],
)
def test_invalid_features_rejected(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(PolicyError, match=match):
        feature(**changes)


@pytest.mark.parametrize("changes", [{"eligible": None}, {"rs60": None}, {"ret60": None}, {"ma20": None}, {"ret60": Decimal(0)}])
def test_null_entry_inputs_skip(changes: dict[str, Any]) -> None:
    rule = policy({"A": feature(**changes)})
    assert rule(DecisionContext(snapshot(), ())) == ()
    assert len(rule.reviews[-1].skipped) == 1


def test_future_stale_held_missing_residual_and_pending_stop_explicitly() -> None:
    for timestamp in (stamp(5), stamp(2, "17:00")):
        rule = policy({"A": feature(available_at=timestamp)})
        with pytest.raises(PolicyError, match="current-session"):
            rule(DecisionContext(snapshot(), ()))
        assert rule.reviews[-1].error
    with pytest.raises(PolicyError, match="price must"):
        policy({"A": feature(5)})(DecisionContext(replace(snapshot(day=5), prices={"A": price()}), ()))
    for features, snap, match in [
        ({}, snapshot(holdings={"A": held()}), "current feature"),
        ({"A": feature()}, replace(snapshot(holdings={"A": held()}), prices={}), "current feature"),
        ({"A": feature(ma20=None)}, snapshot(holdings={"A": held(age=252)}), "requires ma20"),
        ({"A": feature()}, snapshot(holdings={"A": held(qty=1500)}), "unsupported residual"),
    ]:
        with pytest.raises(PolicyError, match=match):
            policy(features)(DecisionContext(snap, ()))
    original = policy({"A": feature()})(DecisionContext(snapshot(), ()))[0]
    pending = (PendingRequest(original, 1),)
    with pytest.raises(PolicyError, match="pending"):
        policy({"A": feature()})(DecisionContext(snapshot(), pending))
    with pytest.raises(FrozenInstanceError):
        original_feature = feature()
        original_feature.rs60 = Decimal("0.2")


def test_fresh_instances_have_no_shared_audit_or_portfolio_state() -> None:
    features = {"A": feature()}
    first, second = policy(features), policy(features)
    assert first is not second
    a = first(DecisionContext(snapshot(), ()))
    assert second.reviews == ()
    assert second(DecisionContext(snapshot(), ())) == a
    assert first(DecisionContext(snapshot(), ())) == a  # no remembered positions
    assert len(first.reviews) == 2 and len(second.reviews) == 1


@pytest.mark.parametrize(
    "changes,match",
    [
        ({"review_status": "unknown"}, "review_status"),
        ({"review_status": None}, "review_status"),
        ({"review_status": "confirmed_halt"}, "review_status_source_id"),
        ({"review_status": "resumed_rewarming", "review_status_source_id": " "}, "review_status_source_id"),
        ({"review_status": "confirmed_halt", "review_status_source_id": 1}, "review_status_source_id"),
        ({"review_status_source_id": "synthetic:halt"}, "observed"),
        ({"review_status_source_id": ""}, "observed"),
    ],
)
def test_review_status_requires_explicit_consistent_source(changes: dict[str, Any], match: str) -> None:
    with pytest.raises(PolicyError, match=match):
        feature(**changes)
    assert feature().review_status == "observed"
    assert feature().review_status_source_id is None


def test_confirmed_halt_no_advice_keeps_cash_slots_and_claims() -> None:
    features = {
        "A": feature(review_status="confirmed_halt", review_status_source_id="synthetic:halt:A", ma20=None, ma60=None),
        "B": feature(),
    }
    rule = policy(features)
    snap = snapshot(codes=("A", "B"), cash=40_000_000, holdings={"A": held(age=252)}, claims=frozenset("WXYZ"))
    assert rule(DecisionContext(snap, ())) == ()
    assert any(item.code == "A" and item.reason == "confirmed_halt_no_advice" for item in rule.reviews[-1].skipped)
    assert any(item.code == "B" and item.reason == "no_empty_slot" for item in rule.reviews[-1].skipped)
    assert snap.cash_cents == 40_000_000 and snap.holdings["A"].qty == 1000 and snap.occupied_issuer_codes == frozenset("WXYZ")
    # A supplied mark cannot be converted into sale proceeds during a halt.
    rule = policy(features)
    assert rule(DecisionContext(replace(snap, cash_cents=0, occupied_issuer_codes=frozenset()), ())) == ()
    assert any(item.code == "B" and item.reason == "budget_cannot_fund_cost_inclusive_lot" for item in rule.reviews[-1].skipped)


@pytest.mark.parametrize(
    "problem,match", [("quantity", "residual shares"), ("age", "completed_closes"), ("feature", "current feature"), ("price", "current feature")]
)
def test_confirmed_halt_does_not_bypass_held_input_validation(problem: str, match: str) -> None:
    features = {"A": feature(review_status="confirmed_halt", review_status_source_id="synthetic:halt:A", ma20=None)}
    snap = snapshot(holdings={"A": held()})
    if problem == "quantity":
        snap = replace(snap, holdings={"A": held(qty=1500)})
    elif problem == "age":
        snap = replace(snap, holdings={"A": held(age=-1)})
    elif problem == "feature":
        features = {}
    else:
        snap = replace(snap, prices={})
    with pytest.raises(PolicyError, match=match):
        policy(features)(DecisionContext(snap, ()))


@pytest.mark.parametrize("status", ["confirmed_halt", "resumed_rewarming"])
def test_interruption_states_forbid_new_buys_even_with_full_features(status: str) -> None:
    rule = policy({"A": feature(review_status=status, review_status_source_id="synthetic:interruption:A")})
    assert rule(DecisionContext(snapshot(), ())) == ()
    assert rule.reviews[-1].skipped[0].reason == f"{status}_no_entry"


def test_resumption_uses_policy_specific_average_and_current_raw_sell_limit() -> None:
    features = {"A": feature(review_status="resumed_rewarming", review_status_source_id="synthetic:resume:A", ma20=Decimal("90"), ma60=None)}
    snap = replace(snapshot(holdings={"A": held(qty=3000)}), prices={"A": price(raw=4995, signal="100")})
    assert policy(features, days=20)(DecisionContext(snap, ())) == ()
    rule = policy(features, days=60)
    request = rule(DecisionContext(snap, ()))[0]
    assert (request.intent.side, request.intent.qty, request.intent.limit_price_cents) == ("SELL", 3000, 4500)
    assert rule.reviews[-1].requests[0].reason == "named_interruption_unavailable_exit_average"
    features["A"] = replace(features["A"], ma60=Decimal("80"))
    assert rule(DecisionContext(snap, ())) == ()
    # Once the average is available, the ordinary age/price exits apply.
    features["A"] = replace(features["A"], ma60=Decimal("110"))
    assert rule(DecisionContext(snap, ()))[0].intent.side == "SELL"
    assert rule.reviews[-1].requests[0].reason == "signal_close_below_ma60"


def test_rewarming_exit_never_releases_slot_or_projected_cash() -> None:
    features = {
        "A": feature(review_status="resumed_rewarming", review_status_source_id="synthetic:resume:A", ma20=None),
        "B": feature(),
    }
    snap = snapshot(codes=("A", "B"), cash=40_000_000, holdings={"A": held()}, claims=frozenset("WXYZ"))
    rule = policy(features)
    requests = rule(DecisionContext(snap, ()))
    assert [(item.intent.code, item.intent.side) for item in requests] == [("A", "SELL")]
    assert any(item.code == "B" and item.reason == "no_empty_slot" for item in rule.reviews[-1].skipped)
    rule = policy(features)
    requests = rule(DecisionContext(replace(snap, cash_cents=0, occupied_issuer_codes=frozenset()), ()))
    assert [(item.intent.code, item.intent.side) for item in requests] == [("A", "SELL")]
    assert any(item.code == "B" and item.reason == "budget_cannot_fund_cost_inclusive_lot" for item in rule.reviews[-1].skipped)


def test_absence_return_rechecks_resumption_without_remembering_exit() -> None:
    features = {"A": feature(5, review_status="resumed_rewarming", review_status_source_id="synthetic:resume:A", ma60=None)}
    rule = policy(features, days=60, absent=frozenset({date(2026, 1, 5)}))
    assert rule(DecisionContext(snapshot(day=5, holdings={"A": held()}), ())) == ()
    assert rule.reviews[-1].absent and rule.reviews[-1].requests == ()
    features["A"] = feature(6, review_status="resumed_rewarming", review_status_source_id="synthetic:resume:A", ma60=Decimal("90"))
    assert rule(DecisionContext(snapshot(day=6, holdings={"A": held()}), ())) == ()
    features["A"] = feature(7, review_status="resumed_rewarming", review_status_source_id="synthetic:resume:A", ma60=None)
    request = rule(DecisionContext(snapshot(day=7, holdings={"A": held()}), ()))[0]
    assert request.intent.decision_at == stamp(7)
    features["A"] = feature(8)
    assert rule(DecisionContext(snapshot(day=8, holdings={"A": held()}), ())) == ()


def test_run_chronology_executes_prior_close_advice_only_at_next_session() -> None:
    days = (2, 5, 6)
    frames = []
    for index, day in enumerate(days):
        windows: tuple[ExecutionWindow, ...] = ()
        if index:
            batch = AuctionBatch("TWSE", "regular_open", stamp(day, "08:55"), stamp(day, "09:00"), f"synthetic-{day}")
            windows = (ExecutionWindow(f"window-{day}", (SessionRoute(batch, COSTS),), stamp(day, "13:30"), stamp(day)),)
        frames.append(DayFrame(date(2026, 1, day), stamp(day, "13:30"), stamp(day), {"A": price(day)}, windows))
    created = []

    def fresh() -> Any:
        rule = CloseReviewPolicy(exit_ma_days=20, feature_provider=lambda as_of: {"A": feature(as_of.day)}, costs=COSTS)
        created.append(rule)
        return rule

    def execution(window: Any, account: Any, routes: Any) -> ExecutionEvidence:
        quotes = {
            (route.batch.session_id, "A"): AuctionQuote("TRADED", 10_000, BOUNDS, 3000, "synthetic-next-open", "synthetic-allocation") for route in routes
        }
        return ExecutionEvidence(f"execution-{window.as_of.day}", quotes, (), True, True)

    args: dict[str, Any] = dict(
        initial_cash_cents=40_000_000,
        max_positions=5,
        history_start=stamp(2, "00:00"),
        initial_checkpoint_id="synthetic-initial",
        frames=tuple(frames),
        calendar_id="synthetic-calendar",
        calendar_complete=True,
        scenario=Scenario("baseline", frozenset(), 0),
        decision_factory=fresh,
        execution_provider=execution,
        corporate_provider=lambda since, until, prefix: CorporateEvidence("synthetic-none", (), True),
    )
    result = run_chronology(**args)
    assert result.status == "complete"
    assert len(result.events) == 1
    assert result.events[0]["action"] == "BUY"
    assert result.events[0]["date"] == stamp(5, "09:00").isoformat()
    assert result.snapshots[0].holdings == {}
    assert result.snapshots[1].holdings["A"].qty == 3000
    assert result.decisions[0].requests[0].intent.decision_at == stamp(2)
    assert result.decisions[1].requests == ()  # no add after execution
    assert run_chronology(**args).events == result.events
    assert len(created) == 2 and created[0] is not created[1]


def test_expired_unfilled_buy_during_absence_is_not_replayed_on_return() -> None:
    days = (2, 5, 6)
    frames = []
    for index, day in enumerate(days):
        windows: tuple[ExecutionWindow, ...] = ()
        if index:
            batch = AuctionBatch("TWSE", "regular_open", stamp(day, "08:55"), stamp(day, "09:00"), f"absence-{day}")
            windows = (ExecutionWindow(f"window-{day}", (SessionRoute(batch, COSTS),), stamp(day, "13:30"), stamp(day)),)
        frames.append(DayFrame(date(2026, 1, day), stamp(day, "13:30"), stamp(day), {"A": price(day)}, windows))
    rules = []

    def fresh() -> Any:
        rule = CloseReviewPolicy(
            exit_ma_days=20,
            costs=COSTS,
            absent_dates=frozenset({date(2026, 1, 5)}),
            feature_provider=lambda as_of: {"A": feature(as_of.day, eligible=as_of.day != 6)},
        )
        rules.append(rule)
        return rule

    def execution(window: Any, account: Any, routes: Any) -> ExecutionEvidence:
        quotes = {
            (route.batch.session_id, "A"): AuctionQuote("TRADED", 20_000, BOUNDS, 3000, "synthetic-price-above-limit", "synthetic-allocation")
            for route in routes
        }
        reports = tuple(
            TerminalReport(
                f"expiry-{route.order.order_id}",
                route.order.order_id,
                window.expires_at,
                window.as_of,
                index + 1,
                "EXPIRED",
                0,
                "synthetic-day-order-expiry",
            )
            for index, route in enumerate(routes)
        )
        return ExecutionEvidence("synthetic-unfilled", quotes, reports, True, True)

    result = run_chronology(
        initial_cash_cents=40_000_000,
        max_positions=5,
        history_start=stamp(2, "00:00"),
        initial_checkpoint_id="synthetic-initial",
        frames=tuple(frames),
        calendar_id="synthetic-calendar",
        calendar_complete=True,
        scenario=Scenario("absence", frozenset(), 0),
        decision_factory=fresh,
        execution_provider=execution,
        corporate_provider=lambda since, until, prefix: CorporateEvidence("synthetic-none", (), True),
    )
    assert result.status == "complete", result.stop_reason
    assert result.events == () and result.pending == ()
    assert result.terminations[0].status == "EXPIRED"
    assert len(result.decisions[0].requests) == 1
    assert result.decisions[1].requests == result.decisions[2].requests == ()
    assert rules[0].reviews[1].absent

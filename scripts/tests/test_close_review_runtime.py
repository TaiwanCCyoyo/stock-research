"""Injected H05 runtime observations and shared-core execution, never market runs."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core.attempt_stress import StressInputs
from research_core.auction import AuctionQuote, CostSchedule, RoutedOrder
from research_core.chronology import ChronologyError, CorporateEvidence, CorporateProvider, ExecutionEvidence, ExecutionProvider, ExecutionWindow, Scenario
from research_core.decision import CloseObservation, ExecutionAccountSnapshot
from research_core.execution_prices import PriceLimits
from research_core.order_lifecycle import TerminalReport

LOCATION = Path(__file__).resolve().parents[2] / "tasks" / "20261005-relative-strength-holding" / "runtime.py"
SPEC = importlib.util.spec_from_file_location("close_review_runtime_under_test", LOCATION)
assert SPEC is not None and SPEC.loader is not None
runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runtime
SPEC.loader.exec_module(runtime)
COSTS = CostSchedule(Fraction(1, 100), 2000, 1, "ceil", Fraction(0), 1, "ceil", Fraction(0), 1, "ceil")
TAIPEI = timezone(timedelta(hours=8))
BOUNDS = PriceLimits(Decimal("0.01"), None)
BASELINE = Scenario("synthetic-baseline", frozenset(), 0)
Observations = tuple[pd.DataFrame, pd.DataFrame, tuple[date, ...]]
Calls = list[list[tuple[str, ...]]]


def stamp(day: date, clock: time = time(20)) -> datetime:
    return datetime.combine(day, clock, tzinfo=TAIPEI)


@pytest.fixture
def observations() -> Observations:
    calendar = tuple(value.date() for value in pd.bdate_range("2026-01-01", periods=65))
    raw = pd.DataFrame([
        {
            "Market": "TWSE",
            "Code": "A",
            "Date": pd.Timestamp(day),
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.0,
            "Volume": 300_000,
            "available_at": stamp(day, time(18)),
            "source_id": "synthetic:raw",
        }
        for day in calendar
    ])
    # Hand-supplied feature contract, not a feature builder/market-data calculation.
    panel = pd.DataFrame([
        {
            "Market": "TWSE",
            "Code": "A",
            "Date": pd.Timestamp(day),
            "signal_close": 12.0,
            "ma20": 11.0 if index >= 19 else float("nan"),
            "ma60": 10.0 if index >= 59 else None,
            "ret60": 0.1 if index >= 60 else None,
            "rs60": 1.0 if index >= 60 else None,
            "consecutive_usable": index + 1,
            "rank_eligible": index >= 60,
            "liquidity_twd": 30_000_000.0,
            "eligible": index >= 60,
            "eligibility_reason": "eligible" if index >= 60 else "warmup",
            "available_at": stamp(day, time(18)),
            "source_id": "synthetic:raw",
            "panel_source_id": "synthetic:h05-features:v1",
        }
        for index, day in enumerate(calendar)
    ])
    return raw, panel, calendar


def execution_factory(*, fill: bool = True, calls: Calls | None = None) -> Callable[[], ExecutionProvider]:
    def fresh() -> ExecutionProvider:
        seen: list[tuple[str, ...]]
        if calls is not None:
            calls.append([])
            seen = calls[-1]
        else:
            seen = []

        def provide(window: ExecutionWindow, account: ExecutionAccountSnapshot, routes: tuple[RoutedOrder, ...]) -> ExecutionEvidence:
            seen.append(tuple(route.order.order_id for route in routes))
            quotes = {
                (route.batch.session_id, route.order.code): AuctionQuote(
                    "TRADED",
                    10_000 if fill else 20_000,
                    BOUNDS,
                    route.order.qty,
                    "synthetic:next-open",
                    "synthetic:allocation",
                )
                for route in routes
            }
            reports = (
                ()
                if fill
                else tuple(
                    TerminalReport(
                        f"expiry:{route.order.order_id}",
                        route.order.order_id,
                        window.expires_at,
                        window.as_of,
                        index + 1,
                        "EXPIRED",
                        0,
                        "synthetic:declared-expiry",
                    )
                    for index, route in enumerate(routes)
                )
            )
            return ExecutionEvidence(f"synthetic:{window.window_id}", quotes, reports, True, True)

        return provide

    return fresh


def empty_corporate_factory(*, complete: bool = True) -> Callable[[], CorporateProvider]:
    def fresh() -> CorporateProvider:
        def provide(since: datetime, until: datetime, prefix: tuple[Mapping[str, Any], ...]) -> CorporateEvidence:
            return CorporateEvidence("synthetic:none" if complete else "synthetic:unknown", (), complete)

        return provide

    return fresh


def prepare(observations: Observations, **changes: Any) -> StressInputs:
    raw, panel, calendar = observations
    args: dict[str, Any] = {
        "calendar": calendar,
        "costs": COSTS,
        "execution_factory": execution_factory(),
        "corporate_factory": empty_corporate_factory(),
        "calendar_id": "synthetic:h05",
        "calendar_complete": True,
        "history_start": stamp(calendar[0], time()),
        "exit_ma_days": 20,
    }
    args.update(changes)
    return runtime.prepare_inputs(raw, panel, **args)


def test_current_core_next_session_fill_separates_raw_from_signal_and_freezes_inputs(observations: Observations) -> None:
    raw, panel, calendar = observations
    inputs = prepare(observations)
    raw.loc[:, "Close"] = 200.0
    panel.loc[:, "signal_close"] = 24.0
    assert inputs.frames[0].windows == ()
    assert len(inputs.frames) == 65
    result = inputs.run(BASELINE)
    assert result.status == "complete", result.stop_reason
    assert len(result.events) == 1
    assert result.events[0]["date"] == stamp(calendar[61], time(9)).isoformat()
    assert result.events[0]["qty"] == 3000
    assert result.events[0]["total"] == -303_000
    first = result.decisions[60].requests[0]
    assert first.intent.decision_at == stamp(calendar[60])
    assert first.intent.limit_price_cents == 10_200  # raw 100, never signal 12
    assert inputs.frames[60].prices["A"].signal_close == Decimal("12.0")
    assert result.snapshots[-1].cash_cents == 169_700_000
    assert result.pending == ()


def test_real_h05_runtime_output_reconciles_with_daily_measurement(observations: Observations) -> None:
    # Actual feature-to-policy-to-next-session auction/ledger seam, synthetic prices.
    spec = importlib.util.spec_from_file_location("h05_integrated_measurement", LOCATION.with_name("measurement.py"))
    assert spec is not None and spec.loader is not None
    measurement = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measurement)
    inputs = prepare(observations)
    result = inputs.run(BASELINE)
    report = measurement.measure(result, expected_reviews=[frame.decision_at for frame in inputs.frames])
    assert report["disposition_counts"] == {"hit": 0, "non_hit": 0, "unknown": 1}
    assert report["account"]["net_return"] == pytest.approx(-3000 / 2_000_000)
    assert report["daily"][-1]["attempt_pnl_cents"] == {"0": -300_000}
    assert report["attempts"][0]["exposure_closes"] == 4


def test_unfilled_expiry_and_absence_use_latest_features_without_replay(observations: Observations) -> None:
    _raw, panel, calendar = observations
    panel.loc[62:, "eligible"] = False
    inputs = prepare(observations, execution_factory=execution_factory(fill=False), absent_dates=frozenset({calendar[61]}))
    result = inputs.run(BASELINE)
    assert result.status == "complete", result.stop_reason
    assert result.events == () and result.pending == ()
    assert len(result.terminations) == 1 and result.terminations[0].status == "EXPIRED"
    assert len(result.decisions[60].requests) == 1
    assert all(not decision.requests for decision in result.decisions[61:])


def test_final_review_marks_nav_without_unreachable_new_advice(observations: Observations) -> None:
    _raw, panel, calendar = observations
    panel.loc[:, "eligible"] = False
    panel.loc[64, "eligible"] = True
    result = prepare(observations).run(BASELINE)
    assert result.status == "complete" and result.pending == ()
    assert result.snapshots[-1].as_of == stamp(calendar[-1])
    assert result.snapshots[-1].equity_cents == 200_000_000
    assert all(not decision.requests for decision in result.decisions)


def test_missing_actual_held_mark_stops_instead_of_forward_filling(observations: Observations) -> None:
    raw, _panel, _calendar = observations
    raw.loc[62, "Close"] = float("nan")
    result = prepare(observations).run(BASELINE)
    assert result.status == "incomplete" and result.stop_reason == "missing_close_marks"
    assert len(result.events) == 1


def test_fresh_policy_and_execution_factories_have_separate_audits(observations: Observations) -> None:
    calls: Calls = []
    inputs = prepare(observations, execution_factory=execution_factory(calls=calls))
    first, second = inputs.decision_factory(), inputs.decision_factory()
    first_policy, second_policy = getattr(first, "policy"), getattr(second, "policy")
    assert first is not second and first_policy is not second_policy
    assert first_policy.reviews == second_policy.reviews == ()
    assert inputs.run(BASELINE).events == inputs.run(BASELINE).events
    assert len(calls) == 2 and calls[0] is not calls[1]


def test_feature_provider_refuses_early_or_other_calendar_asof(observations: Observations) -> None:
    _raw, _panel, calendar = observations
    provider = getattr(prepare(observations).decision_factory(), "policy").feature_provider
    assert provider(stamp(calendar[0]))["A"].ret60 is None
    with pytest.raises(runtime.RuntimeBindingError, match="unavailable"):
        provider(stamp(calendar[60], time(17)))
    with pytest.raises(runtime.RuntimeBindingError, match="outside"):
        provider(stamp(calendar[-1] + timedelta(days=10)))


@pytest.mark.parametrize("problem", ["duplicate", "missing", "market", "source", "late", "before_raw"])
def test_keys_identity_and_feature_availability_fail_at_binding(observations: Observations, problem: str) -> None:
    raw, panel, calendar = observations
    if problem == "duplicate":
        panel = pd.concat([panel, panel.iloc[[0]]], ignore_index=True)
    elif problem == "missing":
        panel = panel.iloc[:-1]
    elif problem == "market":
        panel.loc[0, "Market"] = "TPEX"
    elif problem == "source":
        panel.loc[0, "source_id"] = "other-source"
    elif problem == "late":
        panel.loc[0, "available_at"] = stamp(calendar[1])
    else:
        panel.loc[0, "available_at"] = stamp(calendar[0], time(17))
    with pytest.raises(runtime.RuntimeBindingError):
        prepare((raw, panel, calendar))


@pytest.mark.parametrize("missing_route", [False, True])
def test_execution_route_is_checked_against_current_day_not_decision_day(observations: Observations, missing_route: bool) -> None:
    raw, panel, calendar = observations
    if missing_route:
        raw = raw.drop(index=61)
        panel = panel.drop(index=61)
    else:
        raw.loc[61, "Market"] = "TPEX"
        panel.loc[61, "Market"] = "TPEX"
    with pytest.raises(ChronologyError, match="execution route"):
        prepare((raw, panel, calendar)).run(BASELINE)


def test_incomplete_corporate_domain_is_not_inferred_complete(observations: Observations) -> None:
    inputs = prepare(observations, corporate_factory=empty_corporate_factory(complete=False))
    result = inputs.run(BASELINE)
    assert result.status == "incomplete" and result.events == ()


@pytest.mark.parametrize("changes", [{"calendar_complete": False}, {"corporate_factory": None}, {"execution_factory": None}])
def test_explicit_completeness_and_domain_factories_required(observations: Observations, changes: dict[str, Any]) -> None:
    with pytest.raises(runtime.RuntimeBindingError):
        prepare(observations, **changes)


@pytest.mark.parametrize("side", ["before", "after"])
def test_aligned_rows_outside_calendar_are_rejected_not_silently_omitted(observations: Observations, side: str) -> None:
    raw, panel, calendar = observations
    outside = calendar[0] - timedelta(days=1) if side == "before" else calendar[-1] + timedelta(days=1)
    for table in (raw, panel):
        table.loc[0, "Date"] = pd.Timestamp(outside)
        table.loc[0, "available_at"] = stamp(outside, time(18))
    with pytest.raises(runtime.RuntimeBindingError, match=f"outside supplied calendar: {outside}"):
        prepare(observations)


def test_real_feature_builder_panel_feeds_policy_and_next_session_budget(observations: Observations) -> None:
    feature_path = LOCATION.with_name("features.py")
    feature_spec = importlib.util.spec_from_file_location("h05_feature_builder_runtime_integration", feature_path)
    assert feature_spec is not None and feature_spec.loader is not None
    feature_module = importlib.util.module_from_spec(feature_spec)
    sys.modules[feature_spec.name] = feature_module
    feature_spec.loader.exec_module(feature_module)
    raw, _supplied_panel, calendar = observations
    signal = raw.loc[:, ["Code", "Date", "Open", "High", "Low", "Close"]].copy()
    assert isinstance(signal, pd.DataFrame)
    # A causal injected index, 10.0..16.4, deliberately different from raw 100.
    # No adjustment or economic-event truth is inferred from this synthetic scale.
    scales = pd.Series([(10 + index / 10) / 100 for index in range(65)])
    for column in ("Open", "High", "Low", "Close"):
        signal[column] = signal[column] * scales
    panel = feature_module.build_policy_panel(
        raw,
        signal,
        calendar=calendar,
        universe={day: frozenset({"A"}) for day in calendar},
        source_id="synthetic:causal-index:h05",
        raw_volume_unit="shares",
    )
    inputs = prepare((raw, panel, calendar))
    rule = inputs.decision_factory()
    feature = getattr(rule, "policy").feature_provider(stamp(calendar[60]))["A"]
    assert feature.eligible is True
    assert isinstance(feature.rs60, Decimal) and feature.rs60 == Decimal(1)
    assert isinstance(feature.ret60, Decimal) and feature.ret60 > 0
    result = inputs.run(BASELINE)
    assert result.status == "complete", result.stop_reason
    assert all(not decision.requests for decision in result.decisions[:60])
    request = result.decisions[60].requests[0]
    assert request.intent.qty == 3000 and request.intent.limit_price_cents == 10_200
    assert inputs.frames[60].prices["A"].raw_close_cents == 10_000
    assert inputs.frames[60].prices["A"].signal_close == Decimal("16.0")
    assert len(result.events) == 1
    assert result.events[0]["date"] == stamp(calendar[61], time(9)).isoformat()
    assert result.events[0]["total"] == -303_000
    assert -result.events[0]["total"] <= 400_000
    assert result.snapshots[-1].cash_cents == 169_700_000 and result.pending == ()


def test_terminal_share_delivery_cannot_hide_unsupported_residual_holdings(observations: Observations) -> None:
    _raw, _panel, calendar = observations
    grant_at = stamp(calendar[-1], time(7))
    delivery_at = stamp(calendar[-1], time(7, 1))
    scheduled: tuple[dict[str, Any], ...] = (
        {
            "action": "SHARE_ENTITLEMENT",
            "code": "A",
            "date": grant_at.isoformat(),
            "available_at": grant_at.isoformat(),
            "time_basis": "exact",
            "total": 0,
            "entitlement_id": "synthetic:terminal-share-grant",
            "share_numerator": 300,
            "share_denominator": 1,
            "valuation_policy": "same-class-raw-close-cent-half-up",
        },
        {
            "action": "SHARE_DELIVERY",
            "code": "A",
            "date": delivery_at.isoformat(),
            "available_at": delivery_at.isoformat(),
            "time_basis": "exact",
            "total": 0,
            "entitlement_id": "synthetic:terminal-share-grant",
            "qty": 300,
        },
    )
    delivered: list[dict[str, Any]] = []

    def corporate_factory() -> CorporateProvider:
        def provide(since: datetime, until: datetime, prefix: tuple[Mapping[str, Any], ...]) -> CorporateEvidence:
            events = tuple(event for event in scheduled if since < datetime.fromisoformat(event["date"]) <= until)
            delivered.extend(events)
            return CorporateEvidence("synthetic:terminal-share-domain", events, True)

        return provide

    inputs = prepare(observations, corporate_factory=corporate_factory)
    with pytest.raises(ChronologyError, match="A: unsupported residual shares; whole lots required") as failure:
        inputs.run(BASELINE)
    assert isinstance(failure.value.__cause__, runtime._POLICY.PolicyError)
    assert [event["action"] for event in delivered] == ["SHARE_ENTITLEMENT", "SHARE_DELIVERY"]


def leaf(name: str) -> Any:
    path = LOCATION.parent.parent / "20260921-evening-pilot" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"h05_runtime_native_{name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def modeled_plan(calendar: tuple[date, ...], *, halt_index: int = 62, resume_index: int = 63) -> Any:
    valuation = leaf("valuation")
    halt_day = calendar[halt_index]
    source = f"synthetic:bound-halt:A:{halt_day}"
    mark = valuation.ModeledHaltMark(
        10_000,
        Decimal("100"),  # Raw valuation placeholder, never the signal value 12.
        stamp(halt_day, time(13, 30)),
        stamp(halt_day, time(18)),
        f"{valuation.POLICY}|{source}|reference:synthetic:raw",
        stamp(calendar[halt_index - 1], time(13, 30)),
        source,
    )
    return runtime._SESSIONS.SessionPlan(
        calendar,
        {(halt_day, "A"): mark},
        {(halt_day, "A"): ("confirmed_halt", source), (calendar[resume_index], "A"): ("resumed_rewarming", source)},
        {(halt_day, "A"): source},
    )


def halt_row(raw: pd.DataFrame, panel: pd.DataFrame, index: int = 62) -> None:
    raw.loc[index, ["Open", "High", "Low", "Close"]] = float("nan")
    raw.loc[index, "Volume"] = 0
    panel.loc[index, "signal_close"] = float("nan")


def test_bound_halt_values_held_stock_then_resume_missing_average_exits_next_open(observations: Observations) -> None:
    raw, panel, calendar = observations
    original_raw, original_panel = raw.copy(deep=True), panel.copy(deep=True)
    raw, panel = raw.drop(index=62), panel.drop(index=62)
    panel.loc[63, "ma20"] = float("nan")
    plan = modeled_plan(calendar)
    inputs = prepare((raw, panel, calendar), session_plan=plan)
    result = inputs.run(BASELINE)
    assert result.status == "complete", result.stop_reason
    assert result.snapshots[62].holdings["A"].qty == 3000
    assert result.snapshots[62].cash_cents == result.snapshots[61].cash_cents
    assert result.snapshots[62].equity_cents == result.snapshots[61].equity_cents
    assert result.decisions[62].requests == ()
    resumed = result.decisions[63].requests[0]
    assert (resumed.intent.side, resumed.intent.qty, resumed.intent.limit_price_cents) == ("SELL", 3000, 9000)
    assert result.events[-1]["action"] == "SELL"
    assert result.events[-1]["date"] == stamp(calendar[64], time(9)).isoformat()
    assert result.snapshots[-1].holdings == {}
    review_rule = inputs.decision_factory()
    assert isinstance(review_rule, runtime._ReviewRule)
    close_policy = getattr(review_rule, "policy")
    assert isinstance(close_policy, runtime._POLICY.CloseReviewPolicy)
    supplied_feature = close_policy.feature_provider(stamp(calendar[62]))["A"]
    assert supplied_feature.eligible is False and supplied_feature.ma20 is None and supplied_feature.ma60 is None
    assert supplied_feature.review_status == "confirmed_halt"
    pd.testing.assert_frame_equal(observations[0], original_raw)
    pd.testing.assert_frame_equal(observations[1], original_panel)


def test_modeled_marks_cannot_create_entries_or_modify_existing_averages(observations: Observations) -> None:
    raw, panel, calendar = observations
    halt_row(raw, panel)
    panel.loc[60:61, "eligible"] = False
    panel.loc[64, "eligible"] = False
    panel.loc[62, "ma20"] = 11.0
    inputs = prepare(observations, session_plan=modeled_plan(calendar))
    review_rule = inputs.decision_factory()
    assert isinstance(review_rule, runtime._ReviewRule)
    close_policy = getattr(review_rule, "policy")
    assert isinstance(close_policy, runtime._POLICY.CloseReviewPolicy)
    features = close_policy.feature_provider(stamp(calendar[62]))
    assert features["A"].ma20 == Decimal("11.0")  # Mark raw placeholder does not enter the average.
    assert inputs.frames[62].prices["A"].signal_close == Decimal("100")
    result = inputs.run(BASELINE)
    assert result.status == "complete" and result.events == ()
    assert all(not review.requests for review in result.decisions)


@pytest.mark.parametrize("problem", ["type", "calendar", "unknown", "source", "kind", "actual", "outside", "resume_missing", "late"])
def test_session_plan_invalid_identity_or_overwrite_rejected(observations: Observations, problem: str) -> None:
    raw, panel, calendar = observations
    halt_row(raw, panel)
    plan = modeled_plan(calendar)
    key = (calendar[62], "A")
    if problem == "type":
        plan = object()
    elif problem == "calendar":
        plan = replace(plan, calendar=calendar[:-1])
    elif problem == "unknown":
        plan = replace(plan, statuses={key: ("unknown", "source")})
    elif problem == "source":
        plan = replace(plan, confirmed_halts={key: "different-source"})
    elif problem == "kind":
        mark = plan.marks[key]
        plain = CloseObservation(mark.raw_close_cents, mark.signal_close, mark.observed_at, mark.available_at, mark.source_id)
        plan = replace(plan, marks={key: plain})
    elif problem == "actual":
        raw.loc[62, "Close"] = 100.0
    elif problem == "outside":
        outside = calendar[-1] + timedelta(days=1)
        plan = replace(plan, statuses={**plan.statuses, (outside, "A"): ("resumed_rewarming", "source")})
    elif problem == "resume_missing":
        raw.loc[63, "Close"] = float("nan")
    else:
        mark = replace(plan.marks[key], available_at=stamp(calendar[62], time(21)))
        plan = replace(plan, marks={key: mark})
    with pytest.raises(runtime.RuntimeBindingError):
        prepare((raw, panel, calendar), session_plan=plan)


def test_absence_still_requires_held_valuation_mark(observations: Observations) -> None:
    raw, panel, calendar = observations
    halt_row(raw, panel)
    absent = frozenset({calendar[62]})
    unsupported = prepare(observations, absent_dates=absent).run(BASELINE)
    assert unsupported.status == "incomplete" and unsupported.stop_reason == "missing_close_marks"
    result = prepare(observations, absent_dates=absent, session_plan=modeled_plan(calendar)).run(BASELINE)
    assert result.status == "complete", result.stop_reason
    assert result.snapshots[62].holdings["A"].qty == 3000
    assert result.decisions[62].requests == ()


@pytest.mark.parametrize("field", ["Open", "High", "Low", "Close"])
def test_halt_mark_rejects_remaining_raw_prices_even_when_signal_is_missing(observations: Observations, field: str) -> None:
    raw, panel, calendar = observations
    halt_row(raw, panel)
    raw.loc[62, field] = 100.0
    with pytest.raises(runtime.RuntimeBindingError, match="actual raw observation"):
        prepare(observations, session_plan=modeled_plan(calendar))


@pytest.mark.parametrize("volume", [float("nan"), 1])
def test_halt_mark_requires_known_zero_volume(observations: Observations, volume: float) -> None:
    raw, panel, calendar = observations
    halt_row(raw, panel)
    raw.loc[62, "Volume"] = volume
    with pytest.raises(runtime.RuntimeBindingError, match="known zero"):
        prepare(observations, session_plan=modeled_plan(calendar))


@pytest.mark.parametrize("problem", ["availability_day", "reference_naive", "reference_offset", "reference_equal", "reference_future"])
def test_constructed_halt_plan_cannot_hide_wrong_date_or_reference_time(observations: Observations, problem: str) -> None:
    raw, panel, calendar = observations
    halt_row(raw, panel)
    plan = modeled_plan(calendar)
    mark = plan.marks[(calendar[62], "A")]
    # Simulate a malformed injected object, bypassing the leaf constructor to
    # verify the runtime seam independently of leaf validation.
    if problem == "availability_day":
        object.__setattr__(mark, "available_at", stamp(calendar[61], time(18)))
    elif problem == "reference_naive":
        object.__setattr__(mark, "reference_observed_at", mark.reference_observed_at.replace(tzinfo=None))
    elif problem == "reference_offset":
        object.__setattr__(mark, "reference_observed_at", mark.reference_observed_at.astimezone(timezone.utc))
    elif problem == "reference_equal":
        object.__setattr__(mark, "reference_observed_at", mark.observed_at)
    else:
        object.__setattr__(mark, "reference_observed_at", mark.observed_at + timedelta(minutes=1))
    with pytest.raises(runtime.RuntimeBindingError, match="current-day|reference"):
        prepare(observations, session_plan=plan)


def split_factory(day: date, denominator: int) -> Callable[[], CorporateProvider]:
    at = stamp(day, time(7))
    record = {
        "action": "SPLIT",
        "code": "A",
        "date": at.isoformat(),
        "available_at": at.isoformat(),
        "time_basis": "exact",
        "total": 0,
        "ratio_numerator": 1,
        "ratio_denominator": denominator,
        "old_qty": 3000,
        "new_qty": 3000 // denominator,
        "qty": 3000 // denominator - 3000,
    }

    def fresh() -> CorporateProvider:
        def provide(since: datetime, until: datetime, prefix: tuple[Mapping[str, Any], ...]) -> CorporateEvidence:
            events = (record,) if since < at <= until else ()
            return CorporateEvidence("synthetic:split-domain", events, True)

        return provide

    return fresh


@pytest.mark.parametrize("denominator,legs", [(2, [(1000, "regular_open"), (500, "afterhours_odd")]), (6, [(500, "afterhours_odd")])])
def test_native_odd_adapter_splits_only_real_residual_sell_and_executes(observations: Observations, denominator: int, legs: Any) -> None:
    _raw, panel, calendar = observations
    panel.loc[62:, "ma20"] = 13.0
    inputs = prepare(observations, odd_lot_adapter=leaf("odd_lots"), corporate_factory=split_factory(calendar[62], denominator))
    assert len(inputs.frames[0].windows) == 0 and len(inputs.frames[1].windows) == 2
    result = inputs.run(BASELINE)
    assert result.status == "complete", result.stop_reason
    requests = result.decisions[62].requests
    assert [(request.intent.qty, request.venue) for request in requests] == legs
    sells = [record for record in result.events if record["action"] == "SELL"]
    assert [record["qty"] for record in sells] == [quantity for quantity, _venue in legs]
    assert sells[-1]["date"] == stamp(calendar[63], time(14, 30)).isoformat()
    assert result.snapshots[-1].holdings == {}


@pytest.mark.parametrize("denominator,quantity", [(2, 1500), (6, 500)])
def test_opted_in_terminal_odd_quantity_is_marked_without_unreachable_advice(observations: Observations, denominator: int, quantity: int) -> None:
    _raw, _panel, calendar = observations
    inputs = prepare(observations, odd_lot_adapter=leaf("odd_lots"), corporate_factory=split_factory(calendar[-1], denominator))
    result = inputs.run(BASELINE)
    assert result.status == "complete", result.stop_reason
    terminal = result.snapshots[-1]
    assert terminal.holdings["A"].qty == quantity
    assert terminal.equity_cents == terminal.cash_cents + quantity * 10_000
    assert result.decisions[-1].requests == () and result.pending == ()


def test_odd_opt_in_requires_both_explicit_adapter_callables(observations: Observations) -> None:
    with pytest.raises(runtime.RuntimeBindingError, match="odd_lot_adapter"):
        prepare(observations, odd_lot_adapter=object())

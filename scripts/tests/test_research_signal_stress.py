"""Synthetic signal bundles and rerun coverage; no market performance."""

from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest

from research_core.attempt_stress import StressInputs
from research_core.auction import OrderIntent
from research_core.chronology import (
    ChronologyError,
    CorporateEvidence,
    DecisionContext,
    DecisionRule,
    ExecutionEvidence,
    ExecutionProvider,
    ExecutionWindow,
    PriorCloseRequest,
    Scenario,
)
from research_core.decision import ExecutionAccountSnapshot
from research_core.signal_stress import run_signal_omission_stresses
from research_core.signals import SignalIdentity, SignalOmission
from scripts.tests import test_research_attempt_stress as attempts
from scripts.tests import test_research_causal_scenarios as market
from scripts.tests import test_research_chronology as fixture


def with_test_capacity(config: StressInputs) -> StressInputs:
    def factory() -> ExecutionProvider:
        original = config.execution_factory()

        def execution(window: ExecutionWindow, account: ExecutionAccountSnapshot, routes: fixture.Routes) -> ExecutionEvidence:
            evidence = original(window, account, routes)
            return replace(evidence, quotes={key: replace(quote, allocated_shares=100000) for key, quote in evidence.quotes.items()})

        return execution

    return replace(config, execution_factory=factory)


def bundled_inputs() -> StressInputs:
    config = with_test_capacity(attempts.inputs(contingent_add=False))

    def factory() -> DecisionRule:
        original = config.decision_factory()

        def decide(context: DecisionContext) -> fixture.Requests:
            requests = []
            for request in fixture.advised(original(context)):
                intent = request.intent
                retry = intent.side == "BUY" and intent.decision_at.day == 5
                origin = market.stamp(2) if retry else intent.decision_at
                signal = SignalIdentity(f"A-{origin.day}-{intent.side}", "A", intent.side, origin)
                for child in (1, 2):
                    requests.append(replace(request, intent=replace(intent, order_id=f"{intent.order_id}-child-{child}"), signal=signal))
            return tuple(requests)

        return decide

    return replace(config, decision_factory=factory)


def test_bundle_children_and_later_retry_share_one_draw_and_omit_together() -> None:
    config = bundled_inputs()
    result = run_signal_omission_stresses(config, samplers=(SignalOmission("fixed", Fraction(1)),))
    arm = result.arms[0]
    assert result.baseline.status == "complete" and arm.result is not None and arm.result.status == "complete"
    assert arm.generated_signals == arm.omitted_signals == 2
    assert arm.generated_requests == arm.sampled_omitted_requests == 6
    assert arm.realized_signal_rate == 1 and arm.evidence_status == "observed"
    assert arm.result.events == ()
    assert arm.result.matched_omission_ids == arm.result.unmatched_omission_ids == frozenset()
    assert len(arm.result.signal_draws) == 2


def test_zero_realized_omission_is_not_perturbation_evidence() -> None:
    result = run_signal_omission_stresses(bundled_inputs(), samplers=(SignalOmission("fixed", Fraction(0)),))
    arm = result.arms[0]
    assert arm.result is not None and arm.result.status == "complete"
    assert arm.result.events == result.baseline.events
    assert arm.generated_signals == 5 and arm.generated_requests == 12
    assert arm.realized_signal_rate == 0
    assert arm.evidence_status == "insufficient_perturbation" and arm.unavailable_reason == "no_realized_omissions"


def test_no_signals_has_null_realized_rate_and_missing_baseline_stops_arms() -> None:
    empty = replace(bundled_inputs(), decision_factory=lambda: lambda context: ())
    result = run_signal_omission_stresses(empty, samplers=(SignalOmission("fixed", Fraction(1, 10)),))
    assert result.arms[0].realized_signal_rate is None
    assert result.arms[0].unavailable_reason == "no_generated_signals"
    missing = replace(empty, corporate_factory=lambda: lambda since, until, prefix: CorporateEvidence("unknown", (), False))
    result = run_signal_omission_stresses(missing, samplers=(SignalOmission("fixed", Fraction(1, 10)),))
    assert result.arms[0].result is None and result.arms[0].generated_signals is None
    assert result.arms[0].unavailable_reason == "baseline_incomplete"


def test_partial_metadata_cannot_shrink_sampling_denominator() -> None:
    config = bundled_inputs()

    def factory() -> DecisionRule:
        rule = config.decision_factory()

        def decide(context: DecisionContext) -> fixture.Requests:
            requests = fixture.advised(rule(context))
            return (replace(requests[0], signal=None), *requests[1:]) if requests else ()

        return decide

    mixed = replace(config, decision_factory=factory)
    with pytest.raises(ChronologyError, match="every generated request"):
        mixed.run(Scenario("mixed", frozenset(), 0, signal_omission=SignalOmission("fixed", Fraction(1))))
    with pytest.raises(ChronologyError, match="baseline requires metadata"):
        run_signal_omission_stresses(mixed, samplers=(SignalOmission("fixed", Fraction(1, 10)),))


def test_signal_binding_and_first_seen_origin_are_validated() -> None:
    request = PriorCloseRequest(OrderIntent("buy", "A", "BUY", 1000, 30000, market.stamp(2)), "TWSE", "regular_open")
    for signal in (
        SignalIdentity("wrong-code", "B", "BUY", market.stamp(2)),
        SignalIdentity("wrong-side", "A", "SELL", market.stamp(2)),
        SignalIdentity("future", "A", "BUY", market.stamp(5)),
    ):
        with pytest.raises(ChronologyError, match="match request"):
            replace(request, signal=signal)
    old = replace(request, signal=SignalIdentity("old", "A", "BUY", market.stamp(1)))
    config = replace(bundled_inputs(), decision_factory=lambda: lambda context: (old,))
    with pytest.raises(ChronologyError, match="first generated decision"):
        config.run(Scenario("stale", frozenset(), 0))


def test_explicit_and_sampled_overlap_keep_both_causes_without_double_queueing() -> None:
    target = "A-2-BUY-child-1"
    result = bundled_inputs().run(Scenario("both", frozenset({target}), 0, signal_omission=SignalOmission("fixed", Fraction(1))))
    assert result.status == "complete" and result.events == ()
    assert result.matched_omission_ids == frozenset({target})
    assert target in result.sampled_omission_ids
    assert result.decisions[0].omitted_order_ids.count(target) == 1


def test_reused_signal_cannot_change_origin_within_run() -> None:
    config = bundled_inputs()

    def factory() -> DecisionRule:
        original = config.decision_factory()

        def decide(context: DecisionContext) -> fixture.Requests:
            requests = fixture.advised(original(context))
            if context.snapshot.as_of.day == 5:
                return tuple(replace(request, signal=SignalIdentity("A-2-BUY", "A", "BUY", context.snapshot.as_of)) for request in requests)
            return requests

        return decide

    with pytest.raises(ChronologyError, match="reused signal ID"):
        replace(config, decision_factory=factory).run(Scenario("bad-retry", frozenset(), 0))


def test_new_counterfactual_signal_identity_is_checked_across_all_seed_arms() -> None:
    config = bundled_inputs()
    calls = 0

    def factory() -> DecisionRule:
        nonlocal calls
        calls += 1
        current = calls
        original = config.decision_factory()

        def decide(context: DecisionContext) -> fixture.Requests:
            snap = context.snapshot
            if snap.as_of.day == 5 and "A" not in snap.holdings:
                # Intentional non-deterministic corruption: X is absent from
                # baseline and changes code between the two sampled arms.
                code = "B" if current == 2 else "C"
                signal = SignalIdentity("counterfactual-X", code, "BUY", snap.as_of)
                order = OrderIntent(f"new-order-{current}", code, "BUY", 1000, 30000, snap.as_of)
                return (PriorCloseRequest(order, "TWSE", "regular_open", signal),)
            return fixture.advised(original(context))

        return decide

    samplers = (SignalOmission("first-fixed", Fraction(1)), SignalOmission("second-fixed", Fraction(1)))
    with pytest.raises(ChronologyError, match="cross-run signal ID"):
        run_signal_omission_stresses(replace(config, decision_factory=factory), samplers=samplers)


def test_same_seed_rate_nesting_counts_generated_signals_not_fills() -> None:
    config = with_test_capacity(attempts.inputs())

    def factory() -> DecisionRule:
        def decide(context: DecisionContext) -> fixture.Requests:
            if context.snapshot.as_of.day != 2:
                return ()
            return tuple(
                PriorCloseRequest(
                    OrderIntent(f"request-{index}", "A", "BUY", 1000, 30000, context.snapshot.as_of),
                    "TWSE",
                    "regular_open",
                    SignalIdentity(f"signal-{index}", "A", "BUY", context.snapshot.as_of),
                )
                for index in range(100)
            )

        return decide

    low, high = SignalOmission("predeclared-fixture", Fraction(1, 10)), SignalOmission("predeclared-fixture", Fraction(1, 5))
    result = run_signal_omission_stresses(replace(config, decision_factory=factory), samplers=(low, high))
    arms = result.arms
    assert all(arm.generated_signals == 100 and arm.generated_requests == 100 for arm in arms)
    low_run, high_run = arms[0].result, arms[1].result
    assert low_run is not None and high_run is not None
    low_ids = {draw.signal.signal_id for draw in low_run.signal_draws if draw.omitted}
    high_ids = {draw.signal.signal_id for draw in high_run.signal_draws if draw.omitted}
    assert low_ids and low_ids < high_ids
    assert len(low_run.events) < 100 and len(high_run.events) < 100
    assert {draw.signal.signal_id: draw.digest_hex for draw in low_run.signal_draws} == {
        draw.signal.signal_id: draw.digest_hex for draw in high_run.signal_draws
    }


def test_duplicate_sampler_specs_are_rejected_before_running() -> None:
    sampler = SignalOmission("fixed", Fraction(1, 10))
    with pytest.raises(ChronologyError, match="distinct"):
        run_signal_omission_stresses(bundled_inputs(), samplers=(sampler, sampler))

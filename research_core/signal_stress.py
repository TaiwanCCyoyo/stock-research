"""Explicit-seed signal omission reruns; no seed selection or acceptance gate."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from research_core.attempt_stress import StressInputs, check_cross_run_identities
from research_core.chronology import ChronologyError, ChronologyResult, Scenario
from research_core.signals import SignalOmission


@dataclass(frozen=True)
class SignalStressArm:
    sampler: SignalOmission
    result: ChronologyResult | None
    generated_signals: int | None
    omitted_signals: int | None
    generated_requests: int | None
    sampled_omitted_requests: int | None
    realized_signal_rate: Fraction | None
    evidence_status: str
    unavailable_reason: str | None

    @property
    def nominal_rate(self) -> Fraction:
        """The sampler's stated per-signal probability; `realized_signal_rate` is what this arm drew."""
        return self.sampler.rate


@dataclass(frozen=True)
class SignalStressResult:
    baseline: ChronologyResult
    arms: tuple[SignalStressArm, ...]


def run_signal_omission_stresses(inputs: StressInputs, *, samplers: tuple[SignalOmission, ...]) -> SignalStressResult:
    """Run a baseline then each preregisterable sampler independently.

    Fractions are nominal per-signal inclusion probabilities, not forced counts.
    Trace actual generated-signal coverage even when no omission was realized.
    That case cannot provide evidence of perturbation resilience.
    """
    if not isinstance(inputs, StressInputs) or not isinstance(samplers, tuple) or not samplers:
        raise ChronologyError("stress inputs and a nonempty sampler tuple required")
    if any(not isinstance(sampler, SignalOmission) for sampler in samplers) or len(set(samplers)) != len(samplers):
        raise ChronologyError("samplers must be distinct SignalOmission configurations")
    baseline = inputs.run(Scenario("signal-omission-baseline", frozenset(), 0))
    if baseline.status != "complete":
        arms = tuple(SignalStressArm(sampler, None, None, None, None, None, None, "incomplete", "baseline_incomplete") for sampler in samplers)
        return SignalStressResult(baseline, arms)
    if any(request.signal is None for record in baseline.decisions for request in record.requests):
        raise ChronologyError("signal stress baseline requires metadata on every generated request")
    rerun_inputs = inputs.for_rerun(baseline)
    results = []
    for index, sampler in enumerate(samplers):
        result = rerun_inputs.run(Scenario(f"signal-omission-{index}", frozenset(), 0, signal_omission=sampler))
        count = len(result.signal_draws)
        omitted = sum(draw.omitted for draw in result.signal_draws)
        requests = sum(len(record.requests) for record in result.decisions)
        reason = result.stop_reason
        if result.status != "complete":
            evidence_status = "incomplete"
        elif not count:
            evidence_status, reason = "insufficient_perturbation", "no_generated_signals"
        elif not omitted:
            evidence_status, reason = "insufficient_perturbation", "no_realized_omissions"
        else:
            evidence_status = "observed"
        results.append(
            SignalStressArm(
                sampler,
                result,
                count,
                omitted,
                requests,
                len(result.sampled_omission_ids),
                Fraction(omitted, count) if count else None,
                evidence_status,
                reason,
            )
        )
    # After every arm, not during: a new signal ID is compared across arms in one deterministic
    # pass, so the order the samplers were given in cannot change which error is reported.
    check_cross_run_identities(baseline, [arm.result for arm in results if arm.result is not None])
    return SignalStressResult(baseline, tuple(results))

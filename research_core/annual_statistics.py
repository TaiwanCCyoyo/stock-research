"""Small-sample diagnostics for paired annual strategy and benchmark returns.

These diagnostics do not establish that an evaluation period was unseen. The
sign-flip test assumes exchangeable, symmetric paired log excesses under its
null, and the bootstrap treats annual observations as iid. Neither method
corrects for selection or other point-in-time (PIT) bias.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Sequence

import numpy as np

logger = logging.getLogger(__name__)

_SIGN_FLIP_TOLERANCE = 1e-12


def _validated_multipliers(values: Sequence[float], name: str) -> np.ndarray:
    try:
        array = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite positive numbers") from exc
    if array.ndim != 1:
        raise ValueError(f"{name} must be a one-dimensional sequence")
    if not np.all(np.isfinite(array)) or np.any(array <= 0):
        raise ValueError(f"{name} must contain finite positive numbers")
    return array


def _exp_or_infinity(value: float) -> float:
    """Return exp(value), using positive infinity when it exceeds float range."""
    try:
        return math.exp(value)
    except OverflowError:
        return math.inf


def summarize_annual_excess(
    strategy_multipliers: list[float],
    benchmark_multipliers: list[float],
    *,
    seed: int = 20261013,
    resamples: int = 20_000,
) -> dict[str, float | int | tuple[float, float]]:
    """Summarize paired annual excess using log returns.

    ``strategy_multipliers`` and ``benchmark_multipliers`` are same-year gross
    wealth multipliers (for example, 1.1 means a 10% annual return). At least
    two years are required. Exact sign-flip enumeration is limited to 20 years.

    The one-sided sign-flip p-value enumerates every sign assignment of the
    paired annual log excesses and counts statistics greater than or equal to
    the observed mean. Ties use an absolute tolerance of 1e-12 in mean-log
    units. Its null requires exchangeable, symmetric paired log excesses; the
    iid annual bootstrap interval also assumes iid years. These diagnostics do
    not prove that data were unseen, and neither p-values nor the interval
    correct point-in-time (PIT) selection bias.
    """
    strategy = _validated_multipliers(strategy_multipliers, "strategy_multipliers")
    benchmark = _validated_multipliers(benchmark_multipliers, "benchmark_multipliers")
    if len(strategy) != len(benchmark):
        raise ValueError("strategy and benchmark multipliers must have matching lengths")
    n_years = len(strategy)
    if n_years < 2:
        raise ValueError("at least two annual observations are required")
    if n_years > 20:
        raise ValueError("exact sign-flip enumeration supports at most 20 years")
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)) or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    if isinstance(resamples, bool) or not isinstance(resamples, (int, np.integer)) or resamples < 1:
        raise ValueError("resamples must be a positive integer")

    # Subtracting logs avoids overflow in strategy / benchmark for valid floats.
    annual_log_excess = np.log(strategy) - np.log(benchmark)
    mean_log_excess = float(np.mean(annual_log_excess))
    logger.debug(
        "Summarizing paired annual excess: years=%d seed=%d resamples=%d",
        n_years,
        seed,
        resamples,
    )

    observed_tolerance = _SIGN_FLIP_TOLERANCE * max(1.0, abs(mean_log_excess))
    at_least_observed = 0
    for signs in itertools.product((-1.0, 1.0), repeat=n_years):
        permuted_mean = float(np.mean(annual_log_excess * signs))
        if permuted_mean >= mean_log_excess - observed_tolerance:
            at_least_observed += 1
    sign_flip_p_value = at_least_observed / (2**n_years)

    rng = np.random.default_rng(int(seed))
    bootstrap_indices = rng.integers(0, n_years, size=(int(resamples), n_years))
    bootstrap_means = np.mean(annual_log_excess[bootstrap_indices], axis=1)
    low_mean, high_mean = np.quantile(bootstrap_means, (0.025, 0.975))
    bootstrap_ci = (
        _exp_or_infinity(float(low_mean)) - 1.0,
        _exp_or_infinity(float(high_mean)) - 1.0,
    )

    ordered = np.sort(annual_log_excess)
    leave_best_one = float(np.sum(annual_log_excess) - ordered[-1])
    leave_best_two = float(np.sum(annual_log_excess) - ordered[-2] - ordered[-1])
    results: dict[str, float | int | tuple[float, float]] = {
        "annual_geometric_relative_excess": _exp_or_infinity(mean_log_excess) - 1.0,
        "sign_flip_p_value": sign_flip_p_value,
        "bootstrap_ci_95": bootstrap_ci,
        "win_count": int(np.count_nonzero(annual_log_excess > 0)),
        "n_years": n_years,
        "net_log_contribution": float(np.sum(annual_log_excess)),
        "leave_best_one_relative_terminal_multiple": _exp_or_infinity(leave_best_one),
        "leave_best_two_relative_terminal_multiple": _exp_or_infinity(leave_best_two),
    }
    logger.debug(
        "Annual excess summary complete: wins=%d/%d sign_flip_p=%.6g",
        results["win_count"],
        n_years,
        sign_flip_p_value,
    )
    return results


def equity_drawdown(values: list[float]) -> float:
    """Return the most negative peak-to-trough fraction for positive equity.

    ``values`` is an equity sequence that includes its initial equity value.
    This function makes no conversion from annual to daily drawdown.
    """
    equity = _validated_multipliers(values, "values")
    if len(equity) == 0:
        raise ValueError("values must include at least the initial equity")
    running_peaks = np.maximum.accumulate(equity)
    drawdowns = equity / running_peaks - 1.0
    return float(np.min(drawdowns))

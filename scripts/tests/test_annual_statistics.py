import math
from typing import cast

import pytest

from research_core.annual_statistics import equity_drawdown, summarize_annual_excess


def test_all_winning_years_have_exact_one_sided_sign_flip_probability() -> None:
    summary = summarize_annual_excess([1.1, 1.2, 1.05], [1.0, 1.0, 1.0], resamples=100)

    assert summary["win_count"] == 3
    assert summary["n_years"] == 3
    assert summary["sign_flip_p_value"] == 1 / 2**3
    assert summary["annual_geometric_relative_excess"] == pytest.approx(math.exp((math.log(1.1) + math.log(1.2) + math.log(1.05)) / 3) - 1)


def test_opposite_paired_excesses_have_non_significant_zero_mean() -> None:
    summary = summarize_annual_excess([2.0, 1.0], [1.0, 2.0], resamples=100)

    assert summary["net_log_contribution"] == pytest.approx(0.0)
    assert cast(float, summary["sign_flip_p_value"]) >= 0.5


def test_leave_best_years_remove_paired_strategy_and_benchmark_years() -> None:
    strategy = [1.2, 0.9, 1.1]
    benchmark = [1.0, 1.0, 1.0]
    summary = summarize_annual_excess(strategy, benchmark, resamples=100)

    paired_logs = [math.log(s) - math.log(b) for s, b in zip(strategy, benchmark, strict=True)]
    total = sum(paired_logs)
    best = max(paired_logs)
    second_best = sorted(paired_logs)[-2]
    assert summary["leave_best_one_relative_terminal_multiple"] == pytest.approx(math.exp(total - best))
    assert summary["leave_best_two_relative_terminal_multiple"] == pytest.approx(math.exp(total - best - second_best))


def test_bootstrap_interval_is_deterministic_for_seed() -> None:
    args = ([1.1, 0.95, 1.2], [1.0, 1.0, 1.0])

    first = summarize_annual_excess(*args, seed=17, resamples=500)
    second = summarize_annual_excess(*args, seed=17, resamples=500)

    assert first["bootstrap_ci_95"] == second["bootstrap_ci_95"]


@pytest.mark.parametrize(
    ("strategy", "benchmark"),
    [
        ([1.0], [1.0]),
        ([1.0, 1.0], [1.0]),
        ([0.0, 1.0], [1.0, 1.0]),
        ([math.inf, 1.0], [1.0, 1.0]),
        ([math.nan, 1.0], [1.0, 1.0]),
        ([1.0] * 21, [1.0] * 21),
    ],
)
def test_invalid_annual_multipliers_are_rejected(strategy: list[float], benchmark: list[float]) -> None:
    with pytest.raises(ValueError):
        summarize_annual_excess(strategy, benchmark, resamples=10)


def test_equity_drawdown_includes_initial_peak_and_is_negative_fraction() -> None:
    assert equity_drawdown([100.0, 120.0, 90.0, 110.0]) == pytest.approx(-0.25)
    assert equity_drawdown([100.0, 105.0, 110.0]) == 0.0


@pytest.mark.parametrize("values", [[], [0.0, 1.0], [1.0, -1.0], [1.0, math.inf]])
def test_invalid_equity_sequence_is_rejected(values: list[float]) -> None:
    with pytest.raises(ValueError):
        equity_drawdown(values)

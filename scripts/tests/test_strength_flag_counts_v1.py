"""Synthetic integer-count, standardization, uncertainty and cooldown contracts."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from research_core import momentum_only_v1 as momentum
from research_core.multiple_outcomes_v1 import outcomes_for_targets
from research_core.strength_flag_counts_v1 import METRICS, count_stock, estimate, false_abandonment, intervals, summarize_cell, verdict
from research_core.strength_flags_v1 import BatchFlagIndex


def example_stock(n: int = 90) -> tuple[momentum.StockDaily, BatchFlagIndex, np.ndarray]:
    dates = pd.bdate_range("2010-01-04", periods=n)
    close = np.full(n, 10.0)
    close[3:5] = 8.0
    close[9:20] = 20.0
    frame = pd.DataFrame({"Close": close, "SMA20": np.full(n, 9.0), "SMA60": np.full(n, 9.0), "BBLower": np.full(n, 7.0)}, index=dates)
    pivots = pd.DataFrame(columns=pd.Index(["k", "kind", "extreme_index", "confirmation_index", "extreme_date", "confirmed_at", "price"]))
    index = BatchFlagIndex(frame, pivots, max_horizon=504)
    labels, main, full = {}, {}, {}
    for horizon in momentum.HORIZONS:
        for target, values in outcomes_for_targets(close, horizon, momentum.TARGETS).items():
            labels[horizon, target] = np.array([momentum.LABEL_CODES[label] for label in values.label], dtype=np.int8)
            main[horizon, target] = values.main_eligible.to_numpy()
            full[horizon] = values.calendar_full.to_numpy()
    # Custom small horizons make hand-checkable counts while preserving exact label rules.
    for horizon in (20,):
        for target, values in outcomes_for_targets(close, horizon, (2.0,)).items():
            labels[horizon, target] = np.array([momentum.LABEL_CODES[label] for label in values.label], dtype=np.int8)
            main[horizon, target] = values.main_eligible.to_numpy()
            full[horizon] = values.calendar_full.to_numpy()
    members = np.zeros(n, dtype=np.int8)
    members[[0, 3, 24, 25, 48]] = 1
    stock = momentum.StockDaily(
        "2330",
        momentum.split_for_code("2330"),
        np.ones(n, bool),
        np.zeros(n, bool),
        members == 1,
        {name: members.copy() for name in momentum.LOCAL_ATOMS},
        np.zeros(n),
        labels,
        main,
        full,
    )
    return stock, index, momentum.calendar_years(dates)


def test_cooldown_precedes_state_split_and_full_hit_cost_uses_before_hit() -> None:
    stock, flags, years = example_stock()
    counts = count_stock(stock, flags, years, horizons=(20,), targets=(2.0,), landmarks=(5,))
    focus = counts.loc[counts.group_id.eq("CORE") & counts.flag_id.eq("X6_10")]
    full = focus.loc[focus.landmark.eq(20) & focus.basis.eq("cooled")]
    assert full.event_n.sum() == 3, "membership cooldown keeps 0,24,48; split-first would also keep 3"
    l5 = focus.loc[focus.landmark.eq(5) & focus.basis.eq("cooled")]
    assert l5.event_n.sum() == 3 and l5.loc[l5.flag_state.eq("triggered"), "event_n"].sum() == 1
    assert full.loc[full.flag_state.eq("triggered"), "full_hit_n"].sum() == 1
    assert set(counts.loc[counts.flag_id.isin(["Y1", "Y2"]), "flag_state"]) == {"not_applicable"}


def standard_counts() -> np.ndarray:
    counts = np.zeros((4, 5, len(METRICS)), dtype=float)
    for state, rise, known, hit in [(0, 0, 80, 8), (0, 1, 20, 10), (1, 0, 10, 2), (1, 1, 90, 54)]:
        counts[state, rise, METRICS.index("known_n")] = known
        counts[state, rise, METRICS.index("hit_n")] = hit
    return counts


def test_triggered_distribution_weights_and_missing_control_support_is_null() -> None:
    counts = standard_counts()
    rates = estimate(counts)
    assert rates["triggered_hit_rate"] == 0.18 and rates["untriggered_hit_rate"] == 0.56
    assert rates["pooled_difference"] == pytest.approx(-0.38)
    assert rates["standardized_difference"] == pytest.approx(0.8 * (0.1 - 0.2) + 0.2 * (0.5 - 0.6))
    counts[1, 0] = 0
    assert estimate(counts)["standardized_difference"] is None
    counts[0, 0] = 0
    assert estimate(counts)["standardized_difference"] == pytest.approx(-0.1), "zero-weight strata need no comparison support"


def test_paired_bootstraps_are_repeatable_and_report_undefined_draws() -> None:
    counts = np.broadcast_to(standard_counts(), (4, 3, 4, 5, len(METRICS))).copy().astype(np.int64)
    first = intervals(counts, reps=40)
    assert first == intervals(counts, reps=40)
    assert {row["method"] for row in first} == {"stock", "two_way"}
    assert all(row["defined_replicates"] == 40 for row in first)
    assert all(row["upper"] < 0 for row in first if row["metric"] != "hit_rate_ratio")
    counts[1:] = 0
    unknown = intervals(counts, reps=40)
    assert any(row["defined_replicates"] < 40 and row["upper"] is None for row in unknown)


def test_vectorized_bootstrap_matches_independent_scalar_reconstruction() -> None:
    from research_core import count_cube_v1 as cube

    rng = np.random.default_rng(73)
    counts = np.zeros((5, 3, 4, 5, len(METRICS)), dtype=np.int64)
    for stock in range(5):
        for year in range(3):
            for state in (0, 1):
                for rise in range(4):
                    known = int(rng.integers(10, 100))
                    counts[stock, year, state, rise, METRICS.index("known_n")] = known
                    counts[stock, year, state, rise, METRICS.index("hit_n")] = rng.integers(0, known + 1)
    actual = intervals(counts, reps=99)
    for method, seed in (("stock", 20261024), ("two_way", 20261025)):
        sw = cube.bootstrap_weights(5, 99, seed)
        yw = cube.bootstrap_weights(3, 99, seed + 1) if method == "two_way" else None
        totals = cube.resampled_totals(counts.reshape(5, 3, -1), sw, yw).reshape(99, 4, 5, len(METRICS))
        scalar = [estimate(sample) for sample in totals]
        for metric in ("pooled_difference", "hit_rate_ratio", "standardized_difference"):
            expected = cube.percentile_interval(np.array([sample[metric] for sample in scalar], dtype=float))
            row = next(row for row in actual if row["method"] == method and row["metric"] == metric)
            assert row["defined_replicates"] == 99
            assert (row["lower"], row["upper"]) == pytest.approx(expected, abs=1e-14)


def test_false_abandonment_denominator_and_unknown_bounds() -> None:
    counts = np.zeros((2, 2, 4, 5, len(METRICS)), dtype=np.int64)
    counts[0, 0, 0, 0, METRICS.index("full_hit_n")] = 2
    counts[0, 0, 1, 0, METRICS.index("full_hit_n")] = 6
    counts[0, 0, 2, 0, METRICS.index("full_hit_n")] = 2
    result = false_abandonment(counts)
    assert result["false_abandonment_rate"] == 0.25
    assert result["false_abandonment_lower"] == 0.2 and result["false_abandonment_upper"] == 0.4


def test_w10_precedence_and_both_uncertainty_methods() -> None:
    counts = np.zeros((30, 2, 4, 5, len(METRICS)), dtype=np.int64)
    counts[:, :, :2, 0, METRICS.index("known_n")] = 2
    bounds = [
        {"method": method, "metric": metric, "lower": -0.2, "upper": -0.1}
        for method in ("stock", "two_way")
        for metric in ("pooled_difference", "standardized_difference")
    ]
    assert verdict("Y1", counts, bounds) == "not_applicable"
    assert verdict("X7", counts, bounds) == "weakens_beyond_drop"
    bounds[-1]["upper"] = None
    assert verdict("X7", counts, bounds) == "weakens_with_drop"
    bounds[0]["upper"] = 0.1
    assert verdict("X7", counts, bounds) == "unresolved"
    for row in bounds:
        if row["metric"] == "pooled_difference":
            row["lower"] = 0.01
    assert verdict("X7", counts, bounds) == "opposite"
    counts[0] = 0
    assert verdict("X7", counts, bounds) == "inseparable", "29 stocks fails before checking intervals"


def test_empty_cells_retain_landmark_and_both_crc_halves() -> None:
    empty = pd.DataFrame()
    key = {"group_id": "LEAD_B1", "horizon": 126, "target_multiple": 2.0, "landmark": 20, "flag_id": "X7"}
    rows, bounds = summarize_cell(empty, empty, ["1101", "2330"], [2010, 2011], key=key, reps=20)
    assert rows[0]["landmark"] == 20 and rows[0]["primary"]
    assert rows[0]["verdict"] == "inseparable" and rows[0]["triggered_distinct_stock_n"] == 0
    assert {row["split"] for row in rows} == {"all", "development", "cross-check"}
    assert len(bounds) == 6 and all(row["upper"] is None for row in bounds)

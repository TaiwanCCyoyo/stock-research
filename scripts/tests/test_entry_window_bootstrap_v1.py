"""Small artificial count matrices only; no market inputs or result artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import cast

import numpy as np
import pandas as pd
import pytest

from research_core import count_cube_v1 as shared
from research_core import entry_window_bootstrap_v1 as boot
from research_core import entry_window_v1 as entry
from research_core import momentum_only_v1 as canonical
from research_core.multiple_outcomes_v1 import outcomes_for_targets

AXES = boot.CountAxes(("FAKE_A", "FAKE_B", "FAKE_ZERO"), (2019, 2020, 2021), "2019+")
CELL = entry.COMPARISONS[0]
ZERO = (0,) * len(entry.METRICS)
A = (4, 3, 2, 1, 0, 1, 1, 0)  # unknown overlaps censored, rather than a third disjoint class
ABOVE = (3, 2, 1, 0, 1, 0, 1, 0)  # includes one censored hit outside known/hit_n
BELOW = (3, 1, 0, 1, 0, 2, 1, 1)
B = (2, 2, 0, 0, 2, 0, 0, 0)
B_ABOVE = (4, 4, 3, 1, 0, 0, 0, 0)
B_BELOW = (3, 0, 0, 0, 0, 3, 2, 1)


def _add(*vectors: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sum(parts) for parts in zip(*vectors, strict=True))


def _rows(axes: boot.CountAxes = AXES, cell: entry.Comparison = CELL, cadence: str = "daily", *, empty: bool = False) -> list[entry.CountRow]:
    rows = []
    for si, code in enumerate(axes.codes):
        for yi, year in enumerate(axes.years):
            a, hi, lo = (A, ABOVE, BELOW) if (si, yi) == (0, 0) else (B, B_ABOVE, B_BELOW) if (si, yi) == (1, 1) else (ZERO, ZERO, ZERO)
            if empty:
                a, hi, lo = ZERO, ZERO, ZERO
            r = _add(hi, lo)
            for arm, counts in zip(boot.ARMS, (_add(a, r), a, r, hi, lo), strict=True):
                rows.append(entry.CountRow(cell.set_id, cadence, None if arm == "M" else cell.band_id, cell.label, code, year, arm, counts))
    return rows


def _cube(rows: list[entry.CountRow] | None = None) -> boot.CellCube:
    return boot.build_cell_cube(_rows() if rows is None else rows, axes=AXES, cell=CELL, cadence="daily")


def _hand_weights(method: str) -> boot.PairedWeights:
    stock = np.array([[2, 1, 0], [0, 0, 3], [0, 3, 0]], dtype=np.int64)
    year = np.array([[0, 2, 1], [3, 0, 0], [0, 3, 0]], dtype=np.int64) if method == "two_way" else None
    return boot.PairedWeights(AXES, method, boot.SEEDS[method], 3, stock, year)


@pytest.mark.parametrize("method", ["stock", "two_way"])
def test_hand_weighted_totals_rates_differences_and_public_oracles(method: str) -> None:
    cube, weights = _cube(), _hand_weights(method)
    totals = shared.resampled_totals(cube.counts.reshape(3, 3, -1), weights.stock, weights.year).reshape(3, 5, 8)
    expected_m = (29, 18, 9, 5, 4, 9, 8, 3) if method == "stock" else (18, 12, 6, 2, 4, 6, 4, 2)
    expected_a = (10, 8, 4, 2, 2, 2, 2, 0) if method == "stock" else (4, 4, 0, 0, 4, 0, 0, 0)
    np.testing.assert_array_equal(totals[0, 0], expected_m)
    np.testing.assert_array_equal(totals[0, 1], expected_a)
    assert not totals[1].any()  # zero-event stock is part of the fixed universe
    oracle_samples: dict[str, list[float]] = {stat: [] for stat in boot.STATISTICS}
    for rep in range(weights.reps):
        weighted_rows = []
        for row in _rows():
            si, yi = AXES.codes.index(row.security_id), AXES.years.index(row.t0_year)
            multiplier = int(weights.stock[rep, si]) * (int(weights.year[rep, yi]) if weights.year is not None else 1)
            weighted_rows.append(replace(row, counts=tuple(v * multiplier for v in row.counts)))
        oracle = entry.comparison_rates(entry.aggregate_rows(weighted_rows), CELL, "daily", AXES.era)
        if rep == 0:
            assert oracle["quote_accept_rate"] == (10 / 29 if method == "stock" else 2 / 9)
            assert oracle["all_hit_rate"] == 0.5
            assert oracle["accepted_hit_diff"] == (0 if method == "stock" else -0.5)
            assert oracle["rejected_hit_share"] == (5 / 9 if method == "stock" else 1)
        for name, value in oracle.items():
            if value is not None:
                oracle_samples[name].append(value)
    point = entry.comparison_rates(entry.aggregate_rows(_rows()), CELL, "daily", AXES.era)
    result = boot.bootstrap_cell(cube, weights)
    assert tuple(r.statistic for r in result) == boot.STATISTICS
    for interval in result:
        assert interval.point_estimate == point[interval.statistic]
        assert (interval.lower, interval.upper) == shared.percentile_interval(np.array(oracle_samples[interval.statistic]))
        assert interval.valid_replicate_n == len(oracle_samples[interval.statistic]) == 2
        assert interval.null_replicate_n == 1
        assert interval.valid_replicate_n + interval.null_replicate_n == weights.reps
    assert cube.counts.dtype == np.int64 and cube.counts.shape == (3, 3, 5, 8)
    assert not cube.counts[2].any() and not cube.counts[:, 2].any()


def test_summaries_use_stock_unions_and_same_M_known_denominators() -> None:
    rows = _rows()
    # FAKE_A occurs in two years; FAKE_B remains active too.
    for i, row in enumerate(rows):
        if row.security_id == "FAKE_A" and row.t0_year == 2020:
            source = next(r for r in rows if r.security_id == "FAKE_A" and r.t0_year == 2019 and r.arm == row.arm)
            rows[i] = replace(row, counts=source.counts)
    cube = _cube(rows)
    oracle = entry.aggregate_rows(rows)
    assert cube.summaries == {key: oracle[key] for key in cube.summaries}
    key = entry.SummaryKey(CELL.set_id, "daily", None, CELL.label, AXES.era, "M")
    assert cube.summaries[key].distinct_stock_n == 2
    assert cube.summaries[key].known_stock_ids == frozenset(("FAKE_A", "FAKE_B"))
    values = {r.statistic: r.point_estimate for r in boot.bootstrap_cell(cube, _hand_weights("stock"))}
    assert values["all_hit_rate"] == 0.5  # known, not event denominator
    assert values["quote_accept_rate"] == 10 / 29  # event, not known denominator
    assert values["rejected_hit_share"] == 5 / 9  # M hit, not R known
    # Unmasked S is deliberately unrelated and rejected at the cube boundary.
    with pytest.raises(ValueError):
        _cube(rows + [replace(rows[0], arm="S", counts=tuple(v * 10 for v in rows[0].counts))])


@pytest.mark.parametrize("method", ["stock", "two_way"])
def test_shared_weights_across_six_bands_equal_accepted_all_and_row_order(method: str) -> None:
    weights = _hand_weights(method)
    for cell in (c for c in entry.COMPARISONS if c.set_id == "CORE" and c.label == (126, 2.0)):
        rows = []
        for row in _rows(cell=cell):
            counts = (2, 2, 1, 1, 0, 0, 0, 0) if row.arm in ("M", "accepted") and row.security_id != "FAKE_ZERO" else ZERO
            rows.append(replace(row, counts=counts))
        cube = boot.build_cell_cube(rows, axes=AXES, cell=cell, cadence="daily")
        reverse = boot.build_cell_cube(reversed(rows), axes=AXES, cell=cell, cadence="daily")
        assert boot.bootstrap_cell(cube, weights) == boot.bootstrap_cell(reverse, weights)
        for interval in boot.bootstrap_cell(cube, weights):
            if interval.statistic in ("accepted_hit_diff", "accepted_loss_diff"):
                assert (interval.point_estimate, interval.lower, interval.upper) == (0, 0, 0)
                assert interval.valid_replicate_n == 2


@pytest.mark.parametrize("method", ["stock", "two_way"])
def test_pcg64_fixed_draw_order_golden_and_public_stock_parity(method: str) -> None:
    axes = boot.CountAxes(("FAKE_A", "FAKE_B"), (2019, 2020, 2021), "2019+")
    weights = boot.paired_weights(axes, method=method, reps=4)
    rng = np.random.Generator(np.random.PCG64(boot.SEEDS[method]))
    stock_draws = rng.integers(0, 2, size=(4, 2))
    stock = np.array([np.bincount(draw, minlength=2) for draw in stock_draws])
    np.testing.assert_array_equal(weights.stock, stock)
    expected_stock = [[2, 0], [1, 1], [1, 1], [1, 1]] if method == "stock" else [[2, 0], [0, 2], [0, 2], [1, 1]]
    np.testing.assert_array_equal(weights.stock, expected_stock)
    np.testing.assert_array_equal(weights.stock, shared.bootstrap_weights(2, 4, boot.SEEDS[method]))
    if method == "two_way":
        year_draws = rng.integers(0, 3, size=(4, 3))
        np.testing.assert_array_equal(weights.year, [np.bincount(draw, minlength=3) for draw in year_draws])
        np.testing.assert_array_equal(weights.year, [[1, 1, 1], [1, 1, 1], [1, 1, 1], [1, 2, 0]])
    else:
        assert weights.year is None
    again = boot.paired_weights(axes, method=method, reps=4)
    np.testing.assert_array_equal(weights.stock, again.stock)
    np.testing.assert_array_equal(weights.year, again.year)
    other_era = boot.CountAxes(axes.codes, (2010, 2011), "2010-2012")
    np.testing.assert_array_equal(weights.stock, boot.paired_weights(other_era, method=method, reps=4).stock)
    assert weights.generator == boot.GENERATOR and weights.order == boot.ORDER and weights.numpy_version == np.__version__


def test_all_null_intervals_and_json_use_none() -> None:
    cube = _cube(_rows(empty=True))
    for method in boot.SEEDS:
        result = boot.bootstrap_cell(cube, _hand_weights(method))
        for row in result:
            assert (row.point_estimate, row.lower, row.upper, row.valid_replicate_n, row.null_replicate_n) == (None, None, None, 0, 3)
        assert "NaN" not in json.dumps([asdict(row) for row in result], allow_nan=False)


@pytest.mark.parametrize("close,unknown", [([10.0, 11.0], 1), ([10.0, np.nan, 30.0], 1), ([10.0, 20.0], 0)])
def test_public_B1_censored_counts_enter_cube_without_relabeling(close: list[float], unknown: int) -> None:
    prices = np.asarray(close, dtype=np.float64)
    n = len(prices)
    labels, main, full = {}, {}, {}
    for horizon in canonical.HORIZONS:
        for target, frame in outcomes_for_targets(prices, horizon, canonical.TARGETS).items():
            labels[horizon, target] = np.asarray([canonical.LABEL_CODES[v] for v in frame["label"]], dtype=np.int8)
            main[horizon, target] = frame["main_eligible"].to_numpy(dtype=bool)
            full[horizon] = frame["calendar_full"].to_numpy(dtype=bool)
    stock = canonical.StockDaily(
        "FAKE_A",
        "synthetic",
        np.ones(n, dtype=bool),
        np.zeros(n, dtype=bool),
        np.zeros(n, dtype=bool),
        {a: np.ones(n, dtype=np.int8) for a in ("A1", "A2", "A3")},
        np.full(n, np.nan),
        labels,
        main,
        full,
    )
    calendar = pd.date_range("2019-01-01", periods=n)
    # Only the first day is a signal; quote acceptance does not depend on outcomes.
    stock.eligible[1:] = False
    quote = entry.Quotes(
        "FAKE_A",
        calendar,
        np.full(n, 10.0),
        np.full(n, 11.0),
        np.full(n, 9.0),
        np.full(n, 10.0),
        np.zeros(n, dtype=np.int8),
        np.ones(n, dtype=np.int8),
        np.ones(n, dtype=np.int8),
    )
    selected = [
        row
        for row in entry.count_stock(calendar, stock, quote).rows
        if row.set_id == CELL.set_id
        and row.cadence == "daily"
        and row.label == CELL.label
        and ((row.arm == "M" and row.band_id is None) or (row.arm in entry.ARMS and row.band_id == CELL.band_id))
    ]
    axes = boot.CountAxes(("FAKE_A",), (2019,), "2019+")
    cube = boot.build_cell_cube(selected, axes=axes, cell=CELL, cadence="daily")
    np.testing.assert_array_equal(cube.counts[0, 0, :2], [(1, 0, 0, 0, 0, unknown, 1, 0)] * 2)
    result = {row.statistic: row for row in boot.bootstrap_cell(cube, boot.paired_weights(axes, method="stock", reps=2))}
    assert result["quote_accept_rate"].point_estimate == 1
    assert result["all_hit_rate"].point_estimate is None
    assert result["accepted_hit_diff"].lower is result["accepted_hit_diff"].upper is None


@pytest.mark.parametrize("value", [-1, True, 1.0, float("nan"), float("inf"), np.int64(1)])
def test_builder_rejects_non_python_integer_counts(value: object) -> None:
    rows = _rows()
    # Deliberately violate the typed input contract to test runtime rejection.
    rows[0] = replace(rows[0], counts=cast(tuple[int, ...], (value,) + rows[0].counts[1:]))
    with pytest.raises(ValueError, match="Python integers"):
        _cube(rows)


@pytest.mark.parametrize(
    "change", ["duplicate", "missing_zero", "stock", "year", "band", "M_band", "set", "label", "cadence", "arm", "conservation", "unknown"]
)
def test_builder_rejects_missing_or_mixed_rows(change: str) -> None:
    rows = _rows()
    if change == "duplicate":
        rows.append(rows[0])
    elif change == "missing_zero":
        rows.pop()
    elif change == "stock":
        rows[0] = replace(rows[0], security_id="FAKE_OTHER")
    elif change == "year":
        rows[0] = replace(rows[0], t0_year=2018)
    elif change == "band":
        rows[1] = replace(rows[1], band_id="B02")
    elif change == "M_band":
        rows[0] = replace(rows[0], band_id="B01")
    elif change == "set":
        rows[0] = replace(rows[0], set_id="LEAD_B1")
    elif change == "label":
        rows[0] = replace(rows[0], label=(504, 5.0))
    elif change == "cadence":
        rows[0] = replace(rows[0], cadence="cooled20")
    elif change == "arm":
        rows[0] = replace(rows[0], arm="S")
    elif change == "conservation":
        rows[0] = replace(rows[0], counts=A)
    else:
        rows[0] = replace(rows[0], counts=(10, 6, 3, 2, 1, 0, 3, 1))
    with pytest.raises(ValueError):
        _cube(rows)


@pytest.mark.parametrize(
    "codes,years,era",
    [
        ((), (2019,), "2019+"),
        (("B", "A"), (2019,), "2019+"),
        (("A", "A"), (2019,), "2019+"),
        (("",), (2019,), "2019+"),
        (("A",), (), "all"),
        (("A",), (2020, 2019), "all"),
        (("A",), (2019, 2019), "all"),
        (("A",), (True,), "all"),
        (("A",), (2009,), "all"),
        (("A",), (2013,), "2010-2012"),
        (("A",), (2012,), "2013-2018"),
        (("A",), (2018,), "2019+"),
        (("A",), (2019,), "other"),
    ],
)
def test_axes_require_explicit_sorted_full_population(codes: tuple[str, ...], years: tuple[int, ...], era: str) -> None:
    with pytest.raises(ValueError):
        boot.CountAxes(codes, years, era)


@pytest.mark.parametrize(
    "change", ["negative", "bool", "float", "wrong_sum", "wrong_shape", "year_missing", "year_extra", "year_float", "year_sum", "seed", "reps_bool", "method"]
)
def test_malformed_weights_rejected(change: str) -> None:
    weights = _hand_weights("two_way" if change in ("year_missing", "year_float", "year_sum") else "stock")
    if change in ("negative", "bool", "float", "wrong_sum", "wrong_shape"):
        stock = weights.stock.copy()
        if change == "negative":
            stock[0] = [-1, 1, 3]
        elif change == "bool":
            stock = stock.astype(bool)
        elif change == "float":
            stock = stock.astype(float)
        elif change == "wrong_sum":
            stock[0] = [0, 0, 0]
        else:
            stock = stock[:, :2]
        with pytest.raises(ValueError):
            replace(weights, stock=stock)
    else:
        with pytest.raises(ValueError):
            if change == "year_missing":
                replace(weights, year=None)
            elif change == "year_extra":
                replace(weights, year=weights.stock)
            elif change == "year_float":
                replace(weights, year=np.ones((3, 3), dtype=float))
            elif change == "year_sum":
                replace(weights, year=np.zeros((3, 3), dtype=np.int64))
            elif change == "seed":
                replace(weights, seed=1)
            elif change == "reps_bool":
                replace(weights, reps=True)
            else:
                replace(weights, method="other")


def test_wrong_axes_same_shape_and_cube_mutation_are_rejected() -> None:
    cube, weights = _cube(), _hand_weights("stock")
    for axes in (replace(AXES, codes=("FAKE_C", "FAKE_D", "FAKE_ZERO")), replace(AXES, years=(2020, 2021, 2022)), replace(AXES, era="all")):
        with pytest.raises(ValueError, match="axes"):
            boot.bootstrap_cell(cube, replace(weights, axes=axes))
    with pytest.raises(ValueError):
        replace(cube, cell=replace(CELL, primary=False))
    with pytest.raises(ValueError):
        replace(cube, counts=cube.counts.astype(np.int32))
    cube.counts.flags.writeable = True
    cube.counts[0, 0, 0, 0] = -1
    with pytest.raises(ValueError):
        boot.bootstrap_cell(cube, weights)


def test_int32_int64_and_float64_exact_boundaries() -> None:
    axes = boot.CountAxes(("FAKE_A",), (2019,), "2019+")
    for n in (2**31 + 7, boot.MAX_EXACT_INTEGER):
        rows = _rows(axes)
        for i, row in enumerate(rows):
            rows[i] = replace(row, counts=(n, n, n, 0, 0, 0, 0, 0) if row.arm in ("M", "accepted") else ZERO)
        cube = boot.build_cell_cube(rows, axes=axes, cell=CELL, cadence="daily")
        assert cube.summaries[entry.SummaryKey(CELL.set_id, "daily", None, CELL.label, axes.era, "M")].counts[0] == n
        assert all(row.lower == row.upper for row in boot.bootstrap_cell(cube, boot.paired_weights(axes, method="stock", reps=2)))
    for n in (2**53, boot.MAX_INT64):
        rows = [replace(row, counts=(n, n, n, 0, 0, 0, 0, 0) if row.arm in ("M", "accepted") else ZERO) for row in _rows(axes)]
        cube = boot.build_cell_cube(rows, axes=axes, cell=CELL, cadence="daily")
        with pytest.raises(OverflowError, match="exact float64"):
            boot.bootstrap_cell(cube, boot.paired_weights(axes, method="two_way", reps=2))
    rows[0] = replace(rows[0], counts=(2**63, 2**63, 2**63, 0, 0, 0, 0, 0))
    with pytest.raises(OverflowError, match="int64 before casting"):
        boot.build_cell_cube(rows, axes=axes, cell=CELL, cadence="daily")
    rows = [replace(row, counts=(boot.MAX_INT64, boot.MAX_INT64, boot.MAX_INT64, 0, 0, 0, 0, 0) if row.arm in ("M", "accepted") else ZERO) for row in _rows()]
    huge = _cube(rows)
    key = entry.SummaryKey(CELL.set_id, "daily", None, CELL.label, AXES.era, "M")
    assert huge.summaries[key].counts[0] == 9 * boot.MAX_INT64  # Python integer sum cannot wrap
    with pytest.raises(OverflowError):
        boot.bootstrap_cell(huge, _hand_weights("stock"))
    # Values individually fit float64 exactly, but the paired product bound does not.
    n = 2**51
    rows = [replace(row, counts=(n, n, n, 0, 0, 0, 0, 0) if row.arm in ("M", "accepted") else ZERO) for row in _rows()]
    with pytest.raises(OverflowError, match="weighted count bound"):
        boot.bootstrap_cell(_cube(rows), _hand_weights("two_way"))


def test_fixed_matrix_including_empty_cells_and_default_2000_replicates() -> None:
    seen = set()
    for era, years in (("all", (2010, 2019)), ("2010-2012", (2010, 2012)), ("2013-2018", (2013, 2018)), ("2019+", (2019, 2020))):
        axes = boot.CountAxes(("FAKE_A", "FAKE_B"), years, era)
        by_method = {method: boot.paired_weights(axes, method=method, reps=2) for method in boot.SEEDS}
        for cell in entry.COMPARISONS:
            for cadence in entry.CADENCES:
                empty = cell.set_id == "LEAD_B1" and era == "2010-2012"
                cube = boot.build_cell_cube(_rows(axes, cell, cadence, empty=empty), axes=axes, cell=cell, cadence=cadence)
                for method, weights in by_method.items():
                    intervals = boot.bootstrap_cell(cube, weights)
                    assert len(intervals) == 10
                    for row in intervals:
                        assert row.primary == cell.primary
                        assert row.valid_replicate_n + row.null_replicate_n == 2
                        if empty:
                            assert row.point_estimate is row.lower is row.upper is None
                        seen.add((row.cell_id, row.cadence, row.era, row.method, row.statistic))
    assert len(seen) == 36 * 2 * 4 * 2 * 10
    assert sum(c.primary for c in entry.COMPARISONS) == 24 and sum(not c.primary for c in entry.COMPARISONS) == 12
    for method in boot.SEEDS:
        weights = boot.paired_weights(AXES, method=method)
        rows = boot.bootstrap_cell(_cube(), weights)
        assert rows == boot.bootstrap_cell(_cube(), boot.paired_weights(AXES, method=method))
        assert all(r.reps == 2000 and r.seed == boot.SEEDS[method] and r.generator == boot.GENERATOR and r.numpy_version == np.__version__ for r in rows)

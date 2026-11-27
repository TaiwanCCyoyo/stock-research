"""Artificial StockCounts and independent scalar arithmetic; no market readers."""

import builtins
import itertools
from dataclasses import replace
from typing import Any

import numpy as np
import pytest

from research_core import count_cube_v1 as shared
from research_core import multi_timeframe_ma_comparison_v1 as comparison
from research_core import multi_timeframe_ma_counts_v1 as source


def packet(code: str, scale: int = 1) -> source.StockCounts:
    """Distinct arms/labels/cadences, unknown+censored overlap, repeated stocks."""
    counts = np.zeros((6, 2, 8, 17, 12), dtype=np.int64)
    coverage = np.zeros((17, 3), dtype=np.int64)
    states = np.zeros((6, 17, 3), dtype=np.int64)
    members = np.zeros((6, 2, 17, 3), dtype=np.int64)
    for yi in (0, 1, 3, 8, 9, 16):
        coverage[yi] = (1000 * scale, 900 * scale, 100 * scale)
        for gi in range(6):
            raw = (gi + 1) * 30 * scale if gi != 4 else 1000 * scale
            states[gi, yi] = (raw, (1000 * scale - raw) // 2, 1000 * scale - raw - (1000 * scale - raw) // 2)
            for ci in range(2):
                event = (gi + 1) * (12 if ci == 0 else 6) * scale
                if gi == 4 and ci == 0:
                    event = 900 * scale
                members[gi, ci, yi] = (raw, raw if ci == 0 else event, event)
                for li in range(8):
                    full_unknown, censored = scale, 2 * scale
                    known = event - full_unknown - censored
                    hit = (li + yi % 3 + 1) * scale
                    loss = (li % 3 + 1) * scale
                    # The smallest cooled arm remains consistent across labels.
                    hit = min(hit, known // 2)
                    loss = min(loss, known - hit)
                    counts[gi, ci, li, yi] = (event, known, hit, loss, known - hit - loss, 2 * scale, censored, full_unknown, scale, scale, 0, scale)
    return source.StockCounts(code, counts, coverage, states, members)


@pytest.fixture(scope="module")
def inputs() -> tuple[source.StockCounts, ...]:
    b = packet("B", 2)
    # Different stock-level arm rates make incorrect independent resampling visible.
    for yi in (0, 1, 3, 8, 9, 16):
        b.counts[0, :, :, yi, 2] += 1
        b.counts[0, :, :, yi, 3] -= 1
    return b, packet("A", 1), packet("ZERO", 0)


@pytest.fixture(scope="module")
def tables(inputs: tuple[source.StockCounts, ...]) -> comparison.ComparisonTables:
    return comparison.aggregate_counts(codes=("B", "A", "ZERO"), stocks=inputs)


def row(
    tables: comparison.ComparisonTables, *, group: str = "weekly-turn", cadence: str = "daily", era: str = "all", kind: str = "full", li: int = 0
) -> dict[str, Any]:
    horizon, target = source.LABELS[li]
    return next(
        r
        for r in tables.summary
        if (r["group"], r["cadence"], r["era"], r["row_kind"], r["horizon"], r["target"]) == (group, cadence, era, kind, horizon, target)
    )


def scalar_summary(packets: tuple[source.StockCounts, ...], gi: int, ci: int, li: int, years: list[int], kind: str) -> dict[str, Any]:
    active_stocks = list(range(len(packets)))
    chosen_years = years.copy()
    event_sum = sum(int(p.counts[gi, ci, li, y, 0]) for p in packets for y in years)
    if event_sum and kind == "drop_best_year":
        best = min(years, key=lambda y: (-sum(int(p.counts[gi, ci, li, y, 2]) for p in packets), y))
        chosen_years.remove(best)
    if event_sum and kind == "drop_best_stock":
        best = min(active_stocks, key=lambda s: (-sum(int(packets[s].counts[gi, ci, li, y, 2]) for y in years), packets[s].security_id))
        active_stocks.remove(best)
    totals: dict[str, Any] = {
        name: sum(int(packets[s].counts[gi, ci, li, y, mi]) for s in active_stocks for y in chosen_years) for mi, name in enumerate(source.METRICS)
    }
    n = totals["known_n"]
    denominator = n + totals["full_unknown_n"]
    totals.update({
        "distinct_stock_n": sum(any(packets[s].counts[gi, ci, li, y, 0] > 0 for y in chosen_years) for s in active_stocks),
        "hit_rate": totals["hit_n"] / n if n else None,
        "loss_rate": totals["loss_n"] / n if n else None,
        "full_calendar_hit_lower_bound": totals["hit_n"] / denominator if denominator else None,
        "full_calendar_hit_upper_bound": (totals["hit_n"] + totals["full_unknown_n"]) / denominator if denominator else None,
    })
    return totals


def test_full_matrix_and_scalar_oracle(tables: comparison.ComparisonTables, inputs: tuple[source.StockCounts, ...]) -> None:
    assert tables.codes == ("B", "A", "ZERO") and tables.years == source.YEARS
    assert len(tables.summary) == 6 * 2 * 8 * 4 * 3
    assert len(tables.annual) == 6 * 2 * 8 * 17 * 3
    assert len(tables.contrasts) == 4 * 2 * 8 * 2 * 4
    assert len(tables.intervals) == 4 * len(tables.contrasts)
    eras = {"all": list(range(17)), "2010-2012": list(range(3)), "2013-2018": list(range(3, 9)), "2019+": list(range(9, 17))}
    for r in tables.summary:
        gi, ci = source.GROUPS.index(r["group"]), source.CADENCES.index(r["cadence"])
        li = source.LABELS.index((r["horizon"], r["target"]))
        expected = scalar_summary(inputs, gi, ci, li, eras[r["era"]], r["row_kind"])
        assert all(r[k] == v for k, v in expected.items())
    for r in tables.annual:
        expected = scalar_summary(
            inputs,
            source.GROUPS.index(r["group"]),
            source.CADENCES.index(r["cadence"]),
            source.LABELS.index((r["horizon"], r["target"])),
            [r["t0_year"] - 2010],
            r["row_kind"],
        )
        assert all(r[k] == v for k, v in expected.items())
    assert row(tables)["distinct_stock_n"] == 2
    annual_distinct = sum(
        r["distinct_stock_n"]
        for r in tables.annual
        if r["group"] == "weekly-turn" and r["cadence"] == "daily" and r["target"] == 2 and r["horizon"] == 252 and r["row_kind"] == "full"
    )
    assert annual_distinct == 12
    assert row(tables)["event_n"] != row(tables)["known_n"] + row(tables)["unknown_n"] + row(tables)["censored_n"]


def test_contrasts_baseline_cadence_and_cooled_sufficiency(tables: comparison.ComparisonTables) -> None:
    assert sum(c["primary"] for c in tables.contrasts) == 16 * 2 * 4
    for c in tables.contrasts:
        li = source.LABELS.index((c["horizon"], c["target"]))
        a, b = (row(tables, group=c[name], cadence=c["cadence"], era=c["era"], li=li) for name in ("candidate", "baseline"))
        assert c["hit_diff"] == a["hit_rate"] - b["hit_rate"]
        assert c["loss_diff"] == a["loss_rate"] - b["loss_rate"]
        assert c["candidate_known_n"] == a["known_n"] and c["baseline_known_n"] == b["known_n"]
        assert not c["sample_sufficient"] and c["interpretation"] == "inseparable"
    assert row(tables)["known_n"] > 100 and not row(tables)["sample_sufficient"]


def scalar_interval(
    inputs: tuple[source.StockCounts, ...], method: str, era: str, gi: int, bi: int, ci: int, li: int, metric: int
) -> tuple[float | None, float | None, int]:
    """No shared primitives: draw and count using Python lists/loops."""
    rng = np.random.default_rng({"stock": 20261030, "two_way": 20261031}[method])
    stocks = rng.integers(0, len(inputs), size=(2000, len(inputs)))
    years = rng.integers(0, 17, size=(2000, 17)) if method == "two_way" else None
    allowed = {"all": set(range(17)), "2010-2012": set(range(3)), "2013-2018": set(range(3, 9)), "2019+": set(range(9, 17))}[era]
    samples = []
    for rep in range(2000):
        selected_years = list(range(17)) if years is None else list(years[rep])
        totals = []
        for arm in (gi, bi):
            numerator = denominator = 0
            for si in stocks[rep]:
                for yi in selected_years:
                    if yi in allowed:
                        numerator += int(inputs[int(si)].counts[arm, ci, li, yi, metric])
                        denominator += int(inputs[int(si)].counts[arm, ci, li, yi, 1])
            totals.append((numerator, denominator))
        if all(d > 0 for _, d in totals):
            samples.append(totals[0][0] / totals[0][1] - totals[1][0] / totals[1][1])
    if not samples:
        return None, None, 0
    ordered = sorted(samples)

    def quantile(q: float) -> float:
        position = (len(ordered) - 1) * q
        lo = int(position)
        return ordered[lo] + (ordered[min(lo + 1, len(ordered) - 1)] - ordered[lo]) * (position - lo)

    return quantile(0.025), quantile(0.975), len(samples)


@pytest.mark.parametrize("method", ["stock", "two_way"])
@pytest.mark.parametrize("era", ["all", "2010-2012", "2019+"])
@pytest.mark.parametrize("statistic,metric", [("hit_diff", 2), ("loss_diff", 3)])
def test_paired_bootstrap_scalar_oracle(
    tables: comparison.ComparisonTables, inputs: tuple[source.StockCounts, ...], method: str, era: str, statistic: str, metric: int
) -> None:
    r = next(
        r
        for r in tables.intervals
        if (r["candidate"], r["baseline"], r["cadence"], r["target"], r["horizon"], r["era"], r["bootstrap_type"], r["statistic"])
        == ("weekly-turn", "CORE", "cooled", 2, 252, era, method, statistic)
    )
    lo, hi, valid = scalar_interval(inputs, method, era, 0, 5, 1, 0, metric)
    assert r["lower"] == pytest.approx(lo) and r["upper"] == pytest.approx(hi)
    assert r["valid_replicate_n"] == valid and r["null_replicate_n"] == 2000 - valid
    assert r["seed"] == comparison.SEEDS[method] and r["reps"] == 2000
    assert 0 < r["null_replicate_n"] < 2000


def test_chunks_reproducibility_input_immutability_and_no_io(
    tables: comparison.ComparisonTables, inputs: tuple[source.StockCounts, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    before = [[a.tobytes() for a in (p.counts, p.coverage_counts, p.state_counts, p.membership_counts)] for p in inputs]

    def forbidden(*args: object, **kwargs: object) -> Any:
        raise AssertionError("I/O forbidden")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(np, "load", forbidden)
        result = comparison.aggregate_counts(codes=tables.codes, stocks=itertools.chain(inputs[1:], inputs[:1]))
    assert result == tables
    assert before == [[a.tobytes() for a in (p.counts, p.coverage_counts, p.state_counts, p.membership_counts)] for p in inputs]


def test_empty_cells_null_and_drop_best_ties() -> None:
    a, b = packet("A"), packet("B")
    # Equal per-stock hits -> smallest code, despite B preceding A.
    t = comparison.aggregate_counts(codes=("B", "A"), stocks=(b, a))
    assert row(t, kind="drop_best_stock")["removed_stock"] == "A"
    assert row(t, kind="drop_best_year")["removed_year"] == 2018
    assert row(t, kind="drop_best_year", li=7)["removed_year"] == 2010
    empty = next(r for r in t.annual if r["t0_year"] == 2012 and r["row_kind"] == "full")
    assert empty["hit_rate"] is None and empty["distinct_stock_n"] == 0
    z = comparison.aggregate_counts(codes=("ZERO",), stocks=(packet("ZERO", 0),))
    assert all(
        r["hit_rate"] is None and r["full_calendar_hit_upper_bound"] is None and r["removed_stock"] is None and r["removed_year"] is None for r in z.summary
    )
    assert all(r["lower"] is None and r["upper"] is None and r["valid_replicate_n"] == 0 and r["null_replicate_n"] == 2000 for r in z.intervals)
    assert all(r["hit_diff"] is None and len(r["missing_reasons"]) == 2 for r in z.contrasts)


@pytest.mark.parametrize(
    "mode",
    [
        "missing",
        "duplicate",
        "extra",
        "duplicate_codes",
        "empty_codes",
        "padded_code",
        "axis",
        "dtype",
        "shape",
        "negative",
        "partition",
        "excluded",
        "censored",
        "censored_gap",
        "quality",
        "coverage",
        "states",
        "membership",
        "overflow",
    ],
)
def test_reject_malformed(mode: str) -> None:
    p = packet("A")
    codes: tuple[str, ...] = ("A",)
    packets = [p]
    if mode == "missing":
        packets = []
    elif mode == "duplicate":
        packets = [p, p]
    elif mode == "extra":
        packets = [p, packet("X")]
    elif mode == "duplicate_codes":
        codes = ("A", "A")
    elif mode == "empty_codes":
        codes = ()
    elif mode == "padded_code":
        codes = (" A",)
    elif mode == "axis":
        packets = [replace(p, years=tuple(reversed(source.YEARS)))]
    elif mode == "dtype":
        packets = [replace(p, counts=p.counts.astype(np.int32))]
    elif mode == "shape":
        packets = [replace(p, counts=p.counts[..., :8])]
    elif mode == "negative":
        p.counts.flat[0] = -1
    elif mode == "partition":
        p.counts[0, 0, 0, 0, 2] += 1
    elif mode == "excluded":
        p.counts[0, 0, 0, 0, 10] = 1
    elif mode == "censored":
        p.counts[0, 0, 0, 0, 9] += 1
    elif mode == "censored_gap":
        p.counts[0, 0, 0, 0, 9] -= 1
    elif mode == "quality":
        p.counts[0, 0, 0, 0, 11] = 10
    elif mode == "coverage":
        p.coverage_counts[0, 2] += 1
    elif mode == "states":
        p.state_counts[0, 0, 1] += 1
    elif mode == "membership":
        p.membership_counts[0, 0, 0, 2] += 1
    elif mode == "overflow":
        for array in (p.counts, p.coverage_counts, p.state_counts, p.membership_counts):
            array *= 10**13
    with pytest.raises((ValueError, OverflowError)):
        comparison.aggregate_counts(codes=codes, stocks=packets)


def test_shared_generator_extension_retains_integer_seed_stream() -> None:
    rng = np.random.default_rng(20261031)
    stocks = shared.bootstrap_weights(3, 2000, rng)
    years = shared.bootstrap_weights(17, 2000, rng)
    assert np.array_equal(stocks, shared.bootstrap_weights(3, 2000, 20261031))
    oracle = np.random.default_rng(20261031)
    stock_draws = oracle.integers(0, 3, (2000, 3))
    year_draws = oracle.integers(0, 17, (2000, 17))
    assert np.array_equal(stocks, np.array([[list(r).count(i) for i in range(3)] for r in stock_draws]))
    assert np.array_equal(years, np.array([[list(r).count(i) for i in range(17)] for r in year_draws]))


def test_sufficiency_uses_all_event_stocks_and_both_cooled_arms() -> None:
    packets = [packet(f"ARTIFICIAL_{i:02}") for i in range(30)]
    # Stock 30 has events but no known labels. It still counts toward 30 stocks.
    p = packets[-1]
    p.counts[..., 1:5] = 0
    p.counts[..., 7] = p.counts[..., 0] - p.counts[..., 6]
    p.counts[..., 5] = p.counts[..., 7] + p.counts[..., 8]
    t = comparison.aggregate_counts(codes=tuple(p.security_id for p in packets), stocks=packets)
    assert row(t)["cooled_distinct_stock_n"] == 30
    assert row(t)["sample_sufficient"]
    c = next(c for c in t.contrasts if c["candidate"] == "weekly-turn" and c["baseline"] == "CORE" and c["era"] == "all")
    assert c["sample_sufficient"] and c["interpretation"] is None
    # Preserve every population member; only CORE of stock 30 has zero events.
    p.counts[5] = 0
    p.membership_counts[5, :, :, 2] = 0
    t = comparison.aggregate_counts(codes=t.codes, stocks=packets)
    c = next(c for c in t.contrasts if c["candidate"] == "weekly-turn" and c["baseline"] == "CORE" and c["era"] == "all")
    assert c["candidate_cooled_distinct_stock_n"] == 30
    assert c["baseline_cooled_distinct_stock_n"] == 29
    assert not c["sample_sufficient"] and c["interpretation"] == "inseparable"


@pytest.mark.parametrize("method", ["stock", "two_way"])
def test_one_arm_zero_denominator_replicates(method: str) -> None:
    a, b = packet("A"), packet("B", 2)
    # A retains weekly-turn events, but every one is unknown or censored.
    a.counts[0, ..., 1:5] = 0
    a.counts[0, ..., 7] = a.counts[0, ..., 0] - a.counts[0, ..., 6]
    a.counts[0, ..., 5] = a.counts[0, ..., 7] + a.counts[0, ..., 8]
    inputs = (a, b)
    t = comparison.aggregate_counts(codes=("A", "B"), stocks=inputs)
    r = next(
        r
        for r in t.intervals
        if (r["candidate"], r["baseline"], r["cadence"], r["target"], r["horizon"], r["era"], r["bootstrap_type"], r["statistic"])
        == ("weekly-turn", "CORE", "cooled", 2, 252, "all", method, "hit_diff")
    )
    lo, hi, valid = scalar_interval(inputs, method, "all", 0, 5, 1, 0, 2)
    assert r["lower"] == pytest.approx(lo) and r["upper"] == pytest.approx(hi)
    assert r["valid_replicate_n"] == valid and 0 < valid < 2000
    only_a = comparison.aggregate_counts(codes=("A",), stocks=(a,))
    c = next(c for c in only_a.contrasts if c["candidate"] == "weekly-turn" and c["era"] == "all")
    assert c["candidate_known_n"] == 0 < c["baseline_known_n"]
    assert c["hit_diff"] is None and c["missing_reasons"] == ("candidate_zero_known_n",)
    s = row(only_a)
    assert s["full_calendar_hit_lower_bound"] == 0 and s["full_calendar_hit_upper_bound"] == 1

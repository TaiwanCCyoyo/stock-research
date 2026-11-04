"""Pure S7 complete-universe aggregation and fixed paired comparisons.

Only supplied StockCounts are consumed. Scoped S6/M/state/membership totals are
reported; full mask identity, reason audits and source/PIT evidence are unavailable.
No input reader, outcome construction, research verdict or IO is provided.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from research_core import count_cube_v1 as shared
from research_core import multi_timeframe_ma_counts_v1 as source

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "multi-timeframe-ma-comparison.v1"
ERAS = ("all", "2010-2012", "2013-2018", "2019+")
ROW_KINDS = ("full", "drop_best_year", "drop_best_stock")
SEEDS = {"stock": 20261030, "two_way": 20261031}
REPS = 2000
GENERATOR = "numpy.random.Generator(numpy.random.PCG64)"
ORDER = "caller codes; years 2010..2026; all stock draws [rep,stock], then all year draws [rep,year]; era masks after draws"
PRIMARY_LABELS = ((252, 2.0), (504, 5.0))
_I = {name: i for i, name in enumerate(source.METRICS)}


@dataclass(frozen=True)
class ComparisonTables:
    """In-memory rows, with explicit full resampling population and provenance limits."""

    codes: tuple[str, ...]
    years: tuple[int, ...]
    summary: tuple[dict[str, Any], ...]
    annual: tuple[dict[str, Any], ...]
    contrasts: tuple[dict[str, Any], ...]
    intervals: tuple[dict[str, Any], ...]


def _array(values: np.ndarray, shape: tuple[int, ...], name: str) -> None:
    if type(values) is not np.ndarray or values.dtype != np.dtype("int64") or values.shape != shape:
        raise ValueError(f"{name}: exact int64 array with shape {shape} required")
    if np.any(values < 0):
        raise ValueError(f"{name}: negative counts")
    # Guard the validation sums themselves against wraparound.
    if values.size and int(values.max()) > np.iinfo(np.int64).max // 4:
        raise OverflowError(f"{name}: unsupported counts exceed safe partition arithmetic")


def _validate(packet: source.StockCounts) -> None:
    if not isinstance(packet, source.StockCounts):
        raise ValueError("StockCounts required")
    for name in ("groups", "cadences", "labels", "years", "metrics", "coverage_metrics", "state_metrics", "membership_metrics"):
        if getattr(packet, name) != getattr(source, name.upper()):
            raise ValueError(f"code={packet.security_id}: incompatible {name} axis")
    _array(packet.counts, (6, 2, 8, 17, 12), "counts")
    _array(packet.coverage_counts, (17, 3), "coverage_counts")
    _array(packet.state_counts, (6, 17, 3), "state_counts")
    _array(packet.membership_counts, (6, 2, 17, 3), "membership_counts")
    c = packet.counts

    def col(name: str) -> NDArray[np.int64]:
        return c[..., _I[name]]

    if (
        np.any(col("known_n") != col("hit_n") + col("loss_n") + col("flat_win_n"))
        or np.any(col("event_n") != col("known_n") + col("full_unknown_n") + col("censored_n"))
        or np.any(col("unknown_n") != col("full_unknown_n") + col("censored_unknown_n"))
        or np.any(col("censored_unknown_n") + col("censored_observed_hit_n") != col("censored_n"))
        or np.any(col("quality_unknown_n") > col("unknown_n"))
        or np.any(col("excluded_known_n") != 0)
    ):
        raise ValueError(f"code={packet.security_id}: outcome partition mismatch")
    coverage, states, members = packet.coverage_counts, packet.state_counts, packet.membership_counts
    if (
        np.any(coverage[:, 0] != coverage[:, 1] + coverage[:, 2])
        or np.any(states.sum(axis=-1) != coverage[None, :, 0])
        or np.any(members[..., 0] != states[:, None, :, 0])
        or np.any(members[..., 1] > members[..., 0])
        or np.any(members[..., 2] > members[..., 1])
        or np.any(members[..., 2] > coverage[None, None, :, 1])
        or np.any(members[:, 0, :, 0] != members[:, 0, :, 1])
        or np.any(col("event_n") != members[:, :, None, :, 2])
        or np.any(c[:, 1] > c[:, 0])
        or np.any(states[4, :, 0] != coverage[:, 0])
        or np.any(members[4, 0, :, 2] != coverage[:, 1])
    ):
        raise ValueError(f"code={packet.security_id}: coverage/state/membership partition mismatch")


def _population(codes: tuple[str, ...], packets: Iterable[source.StockCounts]) -> tuple[source.StockCounts, ...]:
    if not isinstance(codes, tuple) or not codes or any(not isinstance(c, str) or not c.strip() or c != c.strip() for c in codes):
        raise ValueError("codes must be an explicit nonempty tuple of unpadded stock IDs")
    if len(set(codes)) != len(codes):
        raise ValueError("duplicate codes in complete population")
    found = {}
    for packet in packets:
        _validate(packet)
        if packet.security_id not in codes or packet.security_id in found:
            raise ValueError("unexpected or duplicate StockCounts security_id")
        found[packet.security_id] = packet
    if set(found) != set(codes):
        raise ValueError("missing StockCounts; explicit zero-event packets are required")
    return tuple(found[code] for code in codes)


def _years(era: str) -> NDArray[np.bool_]:
    years = np.array(source.YEARS)
    return {"all": years >= 2010, "2010-2012": years <= 2012, "2013-2018": (years >= 2013) & (years <= 2018), "2019+": years >= 2019}[era]


def _sufficient(row: dict[str, Any]) -> bool:
    return row["known_n"] >= 100 and row["distinct_stock_n"] >= 30


def _row(
    cube: NDArray[np.int64],
    cooled: NDArray[np.int64],
    coverage: NDArray[np.int64],
    states: NDArray[np.int64],
    members: NDArray[np.int64],
    codes: tuple[str, ...],
    years: NDArray[np.bool_],
    kind: str,
) -> dict[str, Any]:
    stock_mask = np.ones(len(codes), dtype=np.bool_)
    year_mask = years.copy()
    removed_year: int | None = None
    removed_stock: str | None = None
    if kind == "drop_best_year":
        selected = shared.best_year(cube[:, years], source.METRICS)
        if selected is not None:
            position = int(np.flatnonzero(years)[selected])
            removed_year = source.YEARS[position]
            year_mask[position] = False
    elif kind == "drop_best_stock":
        selected = shared.best_stock(cube[:, years], source.METRICS, codes)
        if selected is not None:
            removed_stock = codes[selected]
            stock_mask[selected] = False
    values = shared.summarize(cube, source.METRICS, stocks=stock_mask, years=year_mask)
    cooled_values = shared.summarize(cooled, source.METRICS, stocks=stock_mask, years=year_mask)
    scoped_coverage = coverage[stock_mask][:, year_mask].sum(axis=(0, 1), dtype=np.int64)
    scoped_states = states[stock_mask][:, year_mask].sum(axis=(0, 1), dtype=np.int64)
    scoped_members = members[stock_mask][:, year_mask].sum(axis=(0, 1), dtype=np.int64)
    return {
        **values,
        "row_kind": kind,
        "removed_year": removed_year,
        "removed_stock": removed_stock,
        "cooled_known_n": cooled_values["known_n"],
        "cooled_distinct_stock_n": cooled_values["distinct_stock_n"],
        "sample_sufficient": _sufficient(cooled_values),
        "coverage": dict(zip(source.COVERAGE_METRICS, map(int, scoped_coverage), strict=True)),
        "states": dict(zip(source.STATE_METRICS, map(int, scoped_states), strict=True)),
        "membership": dict(zip(source.MEMBERSHIP_METRICS, map(int, scoped_members), strict=True)),
        "coverage_scope": "supplied S6/M totals only; mask identity/reasons, P/rank pool and source/PIT unavailable",
    }


def _difference(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _contrast(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    sufficient = candidate["sample_sufficient"] and baseline["sample_sufficient"]
    reasons = tuple(f"{arm}_zero_known_n" for arm, row in (("candidate", candidate), ("baseline", baseline)) if row["known_n"] == 0)
    return {
        "candidate": candidate["group"],
        "baseline": baseline["group"],
        "cadence": candidate["cadence"],
        "target": candidate["target"],
        "horizon": candidate["horizon"],
        "era": candidate["era"],
        "primary": (candidate["horizon"], candidate["target"]) in PRIMARY_LABELS,
        "hit_diff": _difference(candidate["hit_rate"], baseline["hit_rate"]),
        "loss_diff": _difference(candidate["loss_rate"], baseline["loss_rate"]),
        "candidate_known_n": candidate["known_n"],
        "baseline_known_n": baseline["known_n"],
        "candidate_distinct_stock_n": candidate["distinct_stock_n"],
        "baseline_distinct_stock_n": baseline["distinct_stock_n"],
        "candidate_cooled_known_n": candidate["cooled_known_n"],
        "baseline_cooled_known_n": baseline["cooled_known_n"],
        "candidate_cooled_distinct_stock_n": candidate["cooled_distinct_stock_n"],
        "baseline_cooled_distinct_stock_n": baseline["cooled_distinct_stock_n"],
        "sample_sufficient": sufficient,
        "sample_status": "sufficient" if sufficient else "insufficient",
        "interpretation": None if sufficient else "inseparable",
        "missing_reasons": reasons,
    }


def aggregate_counts(*, codes: tuple[str, ...], stocks: Iterable[source.StockCounts]) -> ComparisonTables:
    """Require every population member, then build the entire frozen matrix.

    Codes retain caller order; packets may arrive in arbitrary order/chunks via
    an iterable. All 17 original-t years, including zero cells, stay in the
    bootstrap population. Drop-best is per arm/label/cadence/reported slice;
    contrasts and intervals use full rows. Daily sufficiency uses cooled counts.
    """
    packets = _population(codes, stocks)
    values = np.stack([p.counts for p in packets])
    coverage = np.stack([p.coverage_counts for p in packets])
    states = np.stack([p.state_counts for p in packets])
    members = np.stack([p.membership_counts for p in packets])
    for name, audit in (("coverage", coverage), ("states", states), ("membership", members)):
        if int(audit.max()) * len(codes) * len(source.YEARS) > np.iinfo(np.int64).max:
            raise OverflowError(f"{name}: aggregate exceeds int64")
    # Shared resampling uses float64. This conservative bound guarantees exact
    # integer totals even with the largest possible stock/year draw weights.
    bound = int(values.max()) * len(codes) * len(source.YEARS) * len(codes) * len(source.YEARS)
    if bound > 2**53 - 1:
        raise OverflowError("weighted count bound exceeds exact float64 integers (2**53-1)")
    summary, annual = [], []
    full = {}
    for gi, group in enumerate(source.GROUPS):
        for ci, cadence in enumerate(source.CADENCES):
            for li, (horizon, target) in enumerate(source.LABELS):
                identity = {"group": group, "cadence": cadence, "target": target, "horizon": horizon}
                for era in ERAS:
                    for kind in ROW_KINDS:
                        row = {
                            **identity,
                            "era": era,
                            **_row(values[:, gi, ci, li], values[:, gi, 1, li], coverage, states[:, gi], members[:, gi, ci], codes, _years(era), kind),
                        }
                        summary.append(row)
                        if kind == "full":
                            full[group, cadence, li, era] = row
                for yi, year in enumerate(source.YEARS):
                    mask = np.arange(len(source.YEARS)) == yi
                    for kind in ROW_KINDS:
                        annual.append({
                            **identity,
                            "t0_year": year,
                            **_row(values[:, gi, ci, li], values[:, gi, 1, li], coverage, states[:, gi], members[:, gi, ci], codes, mask, kind),
                        })
    contrasts = []
    for candidate in source.CANDIDATES:
        for baseline in ("C-base", "CORE"):
            for cadence in source.CADENCES:
                for li in range(len(source.LABELS)):
                    for era in ERAS:
                        contrasts.append(_contrast(full[candidate, cadence, li, era], full[baseline, cadence, li, era]))
    intervals = []
    for method, seed in SEEDS.items():
        rng = np.random.default_rng(seed)
        sw = shared.bootstrap_weights(len(codes), REPS, rng)
        yw = shared.bootstrap_weights(len(source.YEARS), REPS, rng) if method == "two_way" else None
        for era in ERAS:
            # Select by masks, never compress/reindex the resampling population.
            flat = values.transpose(0, 4, 1, 2, 3, 5).reshape(len(codes), len(source.YEARS), -1)
            masked = np.where(_years(era)[None, :, None], flat, 0)
            totals = shared.resampled_totals(masked, sw, yw).reshape(REPS, 6, 2, 8, 12)
            for contrast in (c for c in contrasts if c["era"] == era):
                gi = source.GROUPS.index(contrast["candidate"])
                bi = source.GROUPS.index(contrast["baseline"])
                ci = source.CADENCES.index(contrast["cadence"])
                li = source.LABELS.index((contrast["horizon"], contrast["target"]))
                a, b = totals[:, gi, ci, li], totals[:, bi, ci, li]
                valid = (a[:, _I["known_n"]] > 0) & (b[:, _I["known_n"]] > 0)
                for statistic, numerator in (("hit_diff", "hit_n"), ("loss_diff", "loss_n")):
                    samples = np.full(REPS, np.nan, dtype=np.float64)
                    samples[valid] = a[valid, _I[numerator]] / a[valid, _I["known_n"]] - b[valid, _I[numerator]] / b[valid, _I["known_n"]]
                    lower, upper = shared.percentile_interval(samples)
                    n = int(np.isfinite(samples).sum())
                    intervals.append({
                        **contrast,
                        "bootstrap_type": method,
                        "statistic": statistic,
                        "point_estimate": contrast[statistic],
                        "seed": seed,
                        "reps": REPS,
                        "lower": lower,
                        "upper": upper,
                        "valid_replicate_n": n,
                        "null_replicate_n": REPS - n,
                        "generator": GENERATOR,
                        "draw_order": ORDER,
                        "numpy_version": np.__version__,
                    })
    LOGGER.debug(
        "S7 comparison stocks=%d summary=%d annual=%d contrasts=%d intervals=%d", len(codes), len(summary), len(annual), len(contrasts), len(intervals)
    )
    return ComparisonTables(codes, source.YEARS, tuple(summary), tuple(annual), tuple(contrasts), tuple(intervals))

"""Rates, drop-one sensitivities and cluster bootstraps from stock x year integer counts.

A study counts its events once per stock and t0 year (`[stock, year, metric]` integer
arrays, metric names given by the caller) and derives every reported slice from those
counts: splits and eras are masks over stocks and years, drop-best-year and
drop-best-stock subtract one slice, and bootstraps reweight stocks (and years). Counts
are summed before any rate is formed, so rates never average other rates.

Conventions follow PR17's `pattern_scan_rates_v1.summarize_events`: `known_n` is the
main denominator, a zero denominator gives a null rate, and drop-best-year removes the
year with the most main-denominator hits (ties: earlier year).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import numpy as np
from numpy.typing import NDArray

LOGGER = logging.getLogger(__name__)


def _rate(numerator: float, denominator: float) -> float | None:
    return float(numerator) / float(denominator) if denominator else None


def summarize(
    counts: NDArray[np.integer], metrics: Sequence[str], *, stocks: NDArray[np.bool_] | None = None, years: NDArray[np.bool_] | None = None
) -> dict[str, Any]:
    """Summed counts, rates and stock statistics for one `[stock, year, metric]` cube slice."""
    cube = counts if stocks is None else counts[stocks]
    cube = cube if years is None else cube[:, years]
    totals = {name: int(value) for name, value in zip(metrics, cube.sum(axis=(0, 1)), strict=True)}
    per_stock = cube[:, :, list(metrics).index("event_n")].sum(axis=1)
    active = per_stock[per_stock > 0]
    hits = cube[:, :, list(metrics).index("hit_n")].sum(axis=1)
    top10 = int(np.sort(hits)[::-1][:10].sum())
    known, hit = totals["known_n"], totals["hit_n"]
    potential = known + totals.get("full_unknown_n", 0)
    return {
        **totals,
        "distinct_stock_n": int(len(active)),
        "per_stock_event_count_median": float(np.median(active)) if len(active) else None,
        "per_stock_event_count_max": int(active.max()) if len(active) else None,
        "hit_rate": _rate(hit, known),
        "loss_rate": _rate(totals["loss_n"], known),
        "full_calendar_hit_lower_bound": _rate(hit, potential),
        "full_calendar_hit_upper_bound": _rate(hit + totals.get("full_unknown_n", 0), potential),
        "top10_stock_hit_share": _rate(top10, hit),
    }


def best_year(counts: NDArray[np.integer], metrics: Sequence[str]) -> int | None:
    """Index of the year with the most main-denominator hits; ties pick the earlier year."""
    hits = counts[:, :, list(metrics).index("hit_n")].sum(axis=0)
    return int(np.argmax(hits)) if hits.max(initial=0) > 0 else None


def best_stock(counts: NDArray[np.integer], metrics: Sequence[str], codes: Sequence[str]) -> int | None:
    """Index of the stock with the most main-denominator hits; ties pick the smallest code."""
    hits = counts[:, :, list(metrics).index("hit_n")].sum(axis=1)
    if hits.max(initial=0) <= 0:
        return None
    tied = np.flatnonzero(hits == hits.max())
    return min((int(position) for position in tied), key=lambda position: codes[position])


def bootstrap_weights(n: int, reps: int, seed: int) -> NDArray[np.int32]:
    """Multinomial resample counts: row b says how often each cluster was drawn."""
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n, size=(reps, n))
    weights = np.zeros((reps, n), dtype=np.int32)
    np.add.at(weights, (np.repeat(np.arange(reps), n), draws.ravel()), 1)
    return weights


def resampled_totals(cube: NDArray[np.integer], stock_weights: NDArray[np.integer], year_weights: NDArray[np.integer] | None = None) -> NDArray[np.float64]:
    """`[rep, metric]` totals of a `[stock, year, metric]` cube under cluster weights.

    Stock-only weights redraw whole stock histories. With year weights too, each stock x
    year cell is weighted by the product of its stock's and year's draw counts (two-way
    pigeonhole bootstrap).
    """
    values = cube.astype(np.float64)
    if year_weights is None:
        return np.einsum("bs,sm->bm", stock_weights.astype(np.float64), values.sum(axis=1))
    return np.einsum("bs,sym,by->bm", stock_weights.astype(np.float64), values, year_weights.astype(np.float64))


def percentile_interval(samples: NDArray[np.float64]) -> tuple[float | None, float | None]:
    finite = samples[np.isfinite(samples)]
    if not len(finite):
        return None, None
    low, high = np.percentile(finite, [2.5, 97.5])
    return float(low), float(high)

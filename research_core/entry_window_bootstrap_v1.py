"""Pure paired count-cube bootstrap for entry-window.v1 (synthetic E1-B2a).

Only explicitly selected, complete stock/year/arm rows enter this module. No
reader, signal/label computation, runner, CLI, or market admission is provided.
Contract: tasks/20261027-entry-window/{data-contract,bootstrap-handoff}.md.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from research_core import count_cube_v1 as shared
from research_core import entry_window_v1 as entry

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "entry-window-bootstrap.v1"
ARMS = ("M", "accepted", "rejected", "above", "below")
STATISTICS = (
    "quote_accept_rate",
    "quote_reject_above_rate",
    "quote_reject_below_rate",
    "all_hit_rate",
    "all_loss_rate",
    "accepted_hit_rate",
    "accepted_loss_rate",
    "accepted_hit_diff",
    "accepted_loss_diff",
    "rejected_hit_share",
)
SEEDS = {"stock": 20261028, "two_way": 20261029}
GENERATOR = "numpy.random.Generator(numpy.random.PCG64)"
ORDER = "sorted codes/years; all stock draws [rep,stock], then all year draws [rep,year]"
MAX_INT64 = int(np.iinfo(np.int64).max)
MAX_EXACT_INTEGER = 2**53 - 1


@dataclass(frozen=True)
class CountAxes:
    """Full fixed resampling population, including zero-event stocks and years."""

    codes: tuple[str, ...]
    years: tuple[int, ...]
    era: str

    def __post_init__(self) -> None:
        if not isinstance(self.codes, tuple) or not self.codes or any(not isinstance(c, str) or not c.strip() for c in self.codes):
            raise ValueError("codes must be a nonempty tuple of explicit stock IDs")
        if self.codes != tuple(sorted(set(self.codes))):
            raise ValueError("codes must be sorted and unique")
        if not isinstance(self.years, tuple) or not self.years or any(type(y) is not int for y in self.years):
            raise ValueError("years must be a nonempty tuple of Python integers")
        if self.years != tuple(sorted(set(self.years))):
            raise ValueError("years must be sorted and unique")
        if self.era not in entry.ERAS:
            raise ValueError("unknown era")
        lower, upper = {"all": (2010, None), "2010-2012": (2010, 2012), "2013-2018": (2013, 2018), "2019+": (2019, None)}[self.era]
        if any(y < lower or (upper is not None and y > upper) for y in self.years):
            raise ValueError("year axis is outside its declared era")


def _identity(axes: CountAxes, cell: entry.Comparison, cadence: str) -> None:
    if not isinstance(axes, CountAxes):
        raise ValueError("explicit CountAxes required")
    axes.__post_init__()
    if cell not in entry.COMPARISONS or cadence not in entry.CADENCES:
        raise ValueError("cell and cadence must have their fixed B1 identities")


def _counts(values: tuple[int, ...]) -> None:
    if len(values) != len(entry.METRICS) or any(type(v) is not int or v < 0 for v in values):
        raise ValueError("counts must be nonnegative Python integers in B1 METRICS order")
    if any(v > MAX_INT64 for v in values):
        raise OverflowError("count exceeds int64 before casting")
    event, known, hit, loss, flat, unknown, censored, full_unknown = values
    if known != hit + loss + flat or event != known + full_unknown + censored or not full_unknown <= unknown <= full_unknown + censored:
        raise ValueError("outcome counts do not conserve B1 known/unknown/censored semantics")


def _cube_array(values: NDArray[np.int64], axes: CountAxes) -> None:
    shape = (len(axes.codes), len(axes.years), len(ARMS), len(entry.METRICS))
    if not isinstance(values, np.ndarray) or values.dtype != np.dtype(np.int64) or values.shape != shape:
        raise ValueError(f"cube must have exact int64 dtype and shape {shape}")
    # Python sums also guard validation itself against int64 wraparound.
    for block in values.reshape(-1, len(ARMS), len(entry.METRICS)):
        vectors = [tuple(int(v) for v in arm) for arm in block]
        for vector in vectors:
            _counts(vector)
        m, a, r, above, below = vectors
        if any(m[i] != a[i] + r[i] or r[i] != above[i] + below[i] for i in range(len(entry.METRICS))):
            raise ValueError("each metric must conserve M=accepted+rejected and rejected=above+below")


def _summaries(cube: CellCube, totals: Iterable[Iterable[int]], *, include_stocks: bool) -> dict[entry.SummaryKey, entry.Summary]:
    result = {}
    for ai, (arm, values) in enumerate(zip(ARMS, totals, strict=True)):
        stock_ids: frozenset[str] = frozenset()
        known_ids: frozenset[str] = frozenset()
        if include_stocks:
            stock_ids = frozenset(code for si, code in enumerate(cube.axes.codes) if np.any(cube.counts[si, :, ai, 0] > 0))
            known_ids = frozenset(code for si, code in enumerate(cube.axes.codes) if np.any(cube.counts[si, :, ai, 1] > 0))
        key = entry.SummaryKey(cube.cell.set_id, cube.cadence, None if arm == "M" else cube.cell.band_id, cube.cell.label, cube.era, arm)
        result[key] = entry.Summary(tuple(int(v) for v in values), stock_ids, known_ids)
    return result


@dataclass(frozen=True)
class CellCube:
    axes: CountAxes
    cell: entry.Comparison
    cadence: str
    counts: NDArray[np.int64]

    def __post_init__(self) -> None:
        _identity(self.axes, self.cell, self.cadence)
        _cube_array(self.counts, self.axes)
        values = self.counts.copy()
        values.flags.writeable = False
        object.__setattr__(self, "counts", values)

    @property
    def era(self) -> str:
        return self.axes.era

    @property
    def summaries(self) -> dict[entry.SummaryKey, entry.Summary]:
        """B1 point summaries with stock-ID unions, never annual distinct sums."""
        _cube_array(self.counts, self.axes)
        totals = self.counts.sum(axis=(0, 1), dtype=object)
        return _summaries(self, totals, include_stocks=True)


def build_cell_cube(rows: Iterable[entry.CountRow], *, axes: CountAxes, cell: entry.Comparison, cadence: str) -> CellCube:
    """Require every explicit stock/year/five-arm row, including zero rows.

    The caller selects one cell/cadence/era from B1 StockCounts. Mixed dimensions,
    duplicate keys, and missing keys are errors; this function never fills gaps.
    """
    _identity(axes, cell, cadence)
    stocks, years = {c: i for i, c in enumerate(axes.codes)}, {y: i for i, y in enumerate(axes.years)}
    values = np.zeros((len(stocks), len(years), len(ARMS), len(entry.METRICS)), dtype=np.int64)
    seen: set[tuple[str, int, str]] = set()
    for row in rows:
        if not isinstance(row, entry.CountRow):
            raise ValueError("B1 CountRow required")
        if row.set_id != cell.set_id or row.label != cell.label or row.cadence != cadence or row.arm not in ARMS:
            raise ValueError("row is outside the selected cell/cadence/arms")
        if row.band_id != (None if row.arm == "M" else cell.band_id):
            raise ValueError("M requires band_id=None; other arms require the selected band")
        if row.security_id not in stocks or type(row.t0_year) is not int or row.t0_year not in years:
            raise ValueError("row stock/year is outside the explicit axes")
        key = (row.security_id, row.t0_year, row.arm)
        if key in seen:
            raise ValueError("duplicate stock/year/arm row")
        _counts(row.counts)
        seen.add(key)
        values[stocks[row.security_id], years[row.t0_year], ARMS.index(row.arm)] = row.counts
    if len(seen) != len(stocks) * len(years) * len(ARMS):
        raise ValueError("missing explicit stock/year/arm row (zero rows are required)")
    return CellCube(axes, cell, cadence, values)


def _weights(values: NDArray[np.integer], reps: int, n: int, axis: str) -> None:
    if not isinstance(values, np.ndarray) or values.dtype.kind not in "iu" or values.shape != (reps, n):
        raise ValueError(f"{axis} weights require integer dtype and shape {(reps, n)}")
    if any(any(int(v) < 0 or int(v) > n for v in row) or sum(int(v) for v in row) != n for row in values):
        raise ValueError(f"{axis} weights must be nonnegative draw counts summing to {n} per rep")


@dataclass(frozen=True)
class PairedWeights:
    axes: CountAxes
    method: str
    seed: int
    reps: int
    stock: NDArray[np.integer]
    year: NDArray[np.integer] | None = None
    generator: str = GENERATOR
    order: str = ORDER
    numpy_version: str = np.__version__

    def __post_init__(self) -> None:
        if not isinstance(self.axes, CountAxes):
            raise ValueError("explicit CountAxes required")
        self.axes.__post_init__()
        if self.method not in SEEDS or type(self.seed) is not int or self.seed != SEEDS[self.method]:
            raise ValueError("method requires its fixed seed")
        if type(self.reps) is not int or self.reps < 1:
            raise ValueError("reps must be a positive Python integer")
        if self.generator != GENERATOR or self.order != ORDER or not isinstance(self.numpy_version, str) or not self.numpy_version.strip():
            raise ValueError("explicit fixed generator, draw order and NumPy version required")
        _weights(self.stock, self.reps, len(self.axes.codes), "stock")
        if self.method == "stock":
            if self.year is not None:
                raise ValueError("stock method cannot have year weights")
        elif self.year is None:
            raise ValueError("two_way requires year weights")
        else:
            _weights(self.year, self.reps, len(self.axes.years), "year")
        for name in ("stock", "year"):
            values = getattr(self, name)
            if values is not None:
                frozen = values.astype(np.int64, copy=True)
                frozen.flags.writeable = False
                object.__setattr__(self, name, frozen)


def _draw_counts(rng: np.random.Generator, n: int, reps: int) -> NDArray[np.int64]:
    """Small local adapter: the shared two-axis helper cannot continue one RNG."""
    draws = rng.integers(0, n, size=(reps, n))
    weights = np.zeros((reps, n), dtype=np.int64)
    np.add.at(weights, (np.repeat(np.arange(reps), n), draws.ravel()), 1)
    return weights


def paired_weights(axes: CountAxes, *, method: str, reps: int = 2000) -> PairedWeights:
    """Draw once per era/method and reuse across every cell and cadence.

    PCG64 draws the entire stock matrix first, then the year matrix from the same
    RNG. The same sorted stock axis has the same stock draws across eras; eras
    are not independent. Zero-event stocks/years stay in the population.
    """
    if not isinstance(axes, CountAxes):
        raise ValueError("explicit CountAxes required")
    axes.__post_init__()
    if method not in SEEDS or type(reps) is not int or reps < 1:
        raise ValueError("fixed method and positive Python-integer reps required")
    seed = SEEDS[method]
    rng = np.random.Generator(np.random.PCG64(seed))
    stock = _draw_counts(rng, len(axes.codes), reps)
    year = _draw_counts(rng, len(axes.years), reps) if method == "two_way" else None
    return PairedWeights(axes, method, seed, reps, stock, year)


@dataclass(frozen=True)
class IntervalRow:
    cell_id: str
    primary: bool
    cadence: str
    era: str
    method: str
    statistic: str
    point_estimate: float | None
    seed: int
    reps: int
    lower: float | None
    upper: float | None
    valid_replicate_n: int
    null_replicate_n: int
    generator: str
    order: str
    numpy_version: str


def bootstrap_cell(cube: CellCube, weights: PairedWeights) -> tuple[IntervalRow, ...]:
    """Weight integer counts before B1 rates and public 95% linear percentiles.

    Counts must have a conservative Python-integer weighted bound <=2**53-1
    before entering shared float64 arithmetic. Unsupported large counts raise,
    rather than rounding silently. Distinct-stock thresholds are not resampled.
    """
    _identity(cube.axes, cube.cell, cube.cadence)
    _cube_array(cube.counts, cube.axes)
    # Recheck mutable ndarray contents even if a caller re-enabled write access.
    _weights(weights.stock, weights.reps, len(weights.axes.codes), "stock")
    if weights.method not in SEEDS or weights.seed != SEEDS[weights.method] or type(weights.reps) is not int or weights.reps < 1:
        raise ValueError("invalid paired-weight method/seed/reps")
    if weights.axes != cube.axes:
        raise ValueError("paired-weight axes must exactly match cube identities, including era")
    if weights.method == "stock" and weights.year is not None:
        raise ValueError("stock method cannot have year weights")
    if weights.method == "two_way":
        if weights.year is None:
            raise ValueError("two_way requires year weights")
        _weights(weights.year, weights.reps, len(cube.axes.years), "year")
    summaries = cube.summaries
    multiplier = int(weights.stock.max()) * (int(weights.year.max()) if weights.year is not None else 1)
    if any(v * multiplier > MAX_EXACT_INTEGER for summary in summaries.values() for v in summary.counts):
        raise OverflowError("conservative weighted count bound exceeds exact float64 integers (2**53-1)")
    LOGGER.debug("Bootstrap cell=%s cadence=%s era=%s method=%s reps=%s", cube.cell.cell_id, cube.cadence, cube.era, weights.method, weights.reps)
    flat = cube.counts.reshape(len(cube.axes.codes), len(cube.axes.years), -1)
    totals = shared.resampled_totals(flat, weights.stock, weights.year).reshape(weights.reps, len(ARMS), len(entry.METRICS))
    if not np.isfinite(totals).all() or np.any(totals < 0) or np.any(totals > MAX_EXACT_INTEGER) or np.any(totals != np.floor(totals)):
        raise OverflowError("resampled totals did not preserve exact nonnegative integers")
    point = entry.comparison_rates(summaries, cube.cell, cube.cadence, cube.era)
    samples = {name: np.full(weights.reps, np.nan, dtype=np.float64) for name in STATISTICS}
    for rep, values in enumerate(totals):
        rates = entry.comparison_rates(_summaries(cube, values, include_stocks=False), cube.cell, cube.cadence, cube.era)
        for name in STATISTICS:
            value = rates[name]
            if value is not None:
                samples[name][rep] = value
    intervals = []
    for name, values in samples.items():
        lower, upper = shared.percentile_interval(values)
        valid = int(np.isfinite(values).sum())
        intervals.append(
            IntervalRow(
                cube.cell.cell_id,
                cube.cell.primary,
                cube.cadence,
                cube.era,
                weights.method,
                name,
                point[name],
                weights.seed,
                weights.reps,
                lower,
                upper,
                valid,
                weights.reps - valid,
                weights.generator,
                weights.order,
                weights.numpy_version,
            )
        )
    return tuple(intervals)

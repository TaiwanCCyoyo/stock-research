"""One-group dense integer accumulation with sparse immutable stock counts."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from numbers import Integral
from statistics import median

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core.pattern_scan_rates_v1 import Summary
from research_core.pattern_scan_summary_store_v1 import COUNT_FIELDS, YEARS

LOGGER = logging.getLogger(__name__)
MAX_CELLS = 100_000
INT64_MAX = 2**63 - 1
# Only bounded cell/year positions are narrowed. Event counts remain exact int64;
# stock ordinals use the platform index width, without imposing a stock limit.
_STOCK_EVENT_DTYPE = np.dtype([("cell", np.int32), ("year", np.int8), ("event_n", np.int64)])
_EVENT_INDEX_DTYPE = np.dtype([("stock", np.intp), ("year", np.int8), ("event_n", np.int64)])


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} requires integer values")
    result = int(value)
    if not minimum <= result <= INT64_MAX:
        raise ValueError(f"{name} outside int64 range")
    return result


def counts_to_summary(counts: Mapping[str, int], stock_event_counts: list[int]) -> Summary:
    """Derive identical public rates after integer and per-stock aggregation."""
    result: Summary = {
        field: value for field, value in counts.items() if field not in ("full_potential_unknown_n", "censored_potential_hit_n", "censored_potential_unknown_n")
    }
    result.update(
        distinct_stock_n=len(stock_event_counts),
        per_stock_event_count_median=float(median(stock_event_counts)) if stock_event_counts else None,
        per_stock_event_count_max=max(stock_event_counts, default=0),
    )
    known, full, censored = counts["known_n"], counts["full_main_potential_n"], counts["censored_potential_n"]
    result.update(
        hit_rate=counts["hit_n"] / known if known else None,
        loss_rate=counts["loss_n"] / known if known else None,
        full_calendar_hit_lower_bound=counts["hit_n"] / full if full else None,
        full_calendar_hit_upper_bound=(counts["hit_n"] + counts["full_potential_unknown_n"]) / full if full else None,
        censored_hit_lower_bound=counts["censored_potential_hit_n"] / censored if censored else None,
        censored_hit_upper_bound=(counts["censored_potential_hit_n"] + counts["censored_potential_unknown_n"]) / censored if censored else None,
    )
    return result


class DenseCounts:
    """Bounded one-group/horizon cells; each stock supplies a complete feed once."""

    def __init__(self, cell_ids: tuple[str, ...], horizon: int) -> None:
        if (
            not isinstance(cell_ids, tuple)
            or len(cell_ids) > MAX_CELLS
            or len(set(cell_ids)) != len(cell_ids)
            or any(not isinstance(cell, str) or not cell.strip() for cell in cell_ids)
        ):
            raise ValueError("cell IDs require a unique tuple within MAX_CELLS")
        self.cell_ids = cell_ids
        self.horizon = _integer(horizon, "horizon", minimum=1)
        self._positions = {cell: index for index, cell in enumerate(cell_ids)}
        self._counts: NDArray[np.int64] = np.zeros((len(cell_ids), len(YEARS), len(COUNT_FIELDS)), dtype=np.int64)
        self._stocks: set[str] = set()
        self._stock_events: dict[str, NDArray[np.void]] = {}
        self._event_index: NDArray[np.void] | None = None
        self._cell_offsets: NDArray[np.int64] | None = None
        self._index_builds = 0

    @property
    def memory_nbytes(self) -> int:
        """Numeric storage bytes; Python mapping/string overhead is separate."""
        return (
            self._counts.nbytes
            + sum(records.nbytes for records in self._stock_events.values())
            + (0 if self._event_index is None else self._event_index.nbytes)
            + (0 if self._cell_offsets is None else self._cell_offsets.nbytes)
        )

    @property
    def index_build_count(self) -> int:
        """Diagnostic count of lazy sparse-index builds, independent of timing."""
        return self._index_builds

    def _indexed_events(self) -> tuple[NDArray[np.void], NDArray[np.int64]]:
        if self._event_index is None or self._cell_offsets is None:
            offsets = np.zeros(len(self.cell_ids) + 1, dtype=np.int64)
            for records in self._stock_events.values():
                offsets[1:] += np.bincount(records["cell"], minlength=len(self.cell_ids))
            np.cumsum(offsets, out=offsets)
            size = int(offsets[-1])
            index = np.empty(size, dtype=_EVENT_INDEX_DTYPE)
            heads = offsets[:-1].copy()
            for ordinal, stock in enumerate(sorted(self._stock_events)):
                records = self._stock_events[stock]
                if not len(records):
                    continue
                # Sort at most one stock, then scatter directly into each cell's
                # final slice. Never allocate a whole-market permutation/copy.
                order = np.argsort(records["cell"], kind="stable")
                cells, starts, counts = np.unique(records["cell"][order], return_index=True, return_counts=True)
                destinations = np.repeat(heads[cells] - starts, counts) + np.arange(len(records))
                index["stock"][destinations] = ordinal
                index["year"][destinations] = records["year"][order]
                index["event_n"][destinations] = records["event_n"][order]
                heads[cells] += counts
            index.setflags(write=False)
            offsets.setflags(write=False)
            self._event_index, self._cell_offsets = index, offsets
            self._index_builds += 1
            LOGGER.debug("Built dense sparse-cell index rows=%d cells=%d stocks=%d", size, len(self.cell_ids), len(self._stocks))
        return self._event_index, self._cell_offsets

    def add_stock(self, matrix: pd.DataFrame) -> None:
        required = {"cell_id", "security_id", "year", "horizon", *COUNT_FIELDS}
        if not matrix.columns.is_unique or not required.issubset(matrix):
            raise ValueError("matrix requires unique identity/count columns")
        if matrix.empty:
            return
        securities = matrix["security_id"].unique()
        if len(securities) != 1 or not isinstance(securities[0], str) or not securities[0].strip():
            raise ValueError("matrix must contain one nonblank stock")
        stock = str(securities[0])
        if stock in self._stocks:
            raise ValueError("duplicate complete stock feed")
        if matrix.duplicated(["cell_id", "year"]).any():
            raise ValueError("duplicate cell/year")
        cells: list[int] = []
        years: list[int] = []
        increments: list[tuple[int, ...]] = []
        event_records: list[tuple[int, int, int]] = []
        additions: dict[int, list[int]] = {}
        for cell, year_value, horizon_value, *values in matrix.loc[:, ["cell_id", "year", "horizon", *COUNT_FIELDS]].itertuples(index=False, name=None):
            if not isinstance(cell, str) or cell not in self._positions:
                raise ValueError("unknown cell_id")
            year = _integer(year_value, "year")
            horizon = _integer(horizon_value, "horizon", minimum=1)
            if year not in YEARS or horizon != self.horizon:
                raise ValueError("matrix year/horizon differs from approved group")
            counts = tuple(_integer(value, "counts") for value in values)
            cell_index, year_index = self._positions[cell], year - YEARS[0]
            cells.append(cell_index)
            years.append(year_index)
            increments.append(counts)
            totals = additions.setdefault(cell_index, [0] * len(COUNT_FIELDS))
            for field, value in enumerate(counts):
                totals[field] += value
            if counts[0]:
                event_records.append((cell_index, year_index, counts[0]))
        # Validate all integer arithmetic before changing either global or sparse
        # state. Whole-cell checks also guard sums across the seventeen years.
        for cell, values in additions.items():
            old = self._counts[cell].sum(axis=0)
            if any(value > INT64_MAX - int(old[field]) for field, value in enumerate(values)):
                raise OverflowError("dense count int64 overflow")
        delta = np.asarray(increments, dtype=np.int64)
        cell_positions = np.asarray(cells, dtype=np.int64)
        year_positions = np.asarray(years, dtype=np.int64)
        sparse = np.asarray(event_records, dtype=_STOCK_EVENT_DTYPE)
        sparse.setflags(write=False)
        self._counts[cell_positions, year_positions] += delta
        self._stocks.add(stock)
        self._stock_events[stock] = sparse
        self._event_index = None
        self._cell_offsets = None
        LOGGER.debug("Dense feed stock=%s rows=%d cells=%d sparse_events=%d", stock, len(matrix), len(additions), len(sparse))

    def summarize(self, cell_id: str, exclude_year: int | None = None, only_year: int | None = None) -> Summary:
        if cell_id not in self._positions:
            raise ValueError("unknown cell_id")
        for year in (exclude_year, only_year):
            if year is not None and (_integer(year, "summary year") not in YEARS):
                raise ValueError("summary year must be approved")
        if exclude_year is not None and only_year is not None:
            raise ValueError("choose either excluded or single year")
        selected = np.ones(len(YEARS), dtype=bool)
        if exclude_year is not None:
            selected[exclude_year - YEARS[0]] = False
        if only_year is not None:
            selected[:] = False
            selected[only_year - YEARS[0]] = True
        position = self._positions[cell_id]
        totals = self._counts[position, selected].sum(axis=0)
        counts: dict[str, int] = dict(zip(COUNT_FIELDS, (int(value) for value in totals), strict=True))
        index, offsets = self._indexed_events()
        matching = index[int(offsets[position]) : int(offsets[position + 1])]
        matching = matching[selected[matching["year"]]]
        per_stock = np.zeros(len(self._stocks), dtype=np.int64)
        # Float-weighted bincount loses exact counts above 2**53. Whole-cell
        # overflow validation already guarantees these per-stock sums fit int64.
        np.add.at(per_stock, matching["stock"], matching["event_n"])
        stock_counts = [int(value) for value in per_stock[per_stock > 0]]
        return counts_to_summary(counts, stock_counts)

    def annual_summary(self, cell_id: str) -> tuple[Summary, ...]:
        return tuple(self.summarize(cell_id, only_year=year) for year in YEARS)

    def drop_best_year(self, cell_id: str) -> tuple[int | None, Summary]:
        total = self.summarize(cell_id)
        if not total["event_n"]:
            return None, total
        position = self._positions[cell_id]
        hit_column = COUNT_FIELDS.index("hit_n")
        year = min(YEARS, key=lambda value: (-int(self._counts[position, value - YEARS[0], hit_column]), value))
        return year, self.summarize(cell_id, exclude_year=year)

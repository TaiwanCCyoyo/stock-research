"""Pure in-memory assembly of staged entry-window.v1 counts and intervals.

This engineering boundary accepts already-loaded packets. It has no readers,
label construction, persistence, execution inference, or market admission.
Contracts: tasks/20261027-entry-window/{data-contract,bootstrap-handoff}.md.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import chain
from types import MappingProxyType

import pandas as pd

from research_core import entry_window_bootstrap_v1 as bootstrap
from research_core import entry_window_inputs_v1 as inputs
from research_core import entry_window_v1 as entry
from research_core import momentum_only_v1 as canonical

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "entry-window-assembly.v1"
METHODS = ("stock", "two_way")


@dataclass(frozen=True, kw_only=True)
class AssemblyRequest:
    """Explicit common identity and complete resampling population."""

    codes: tuple[str, ...]
    generation: str
    study_as_of: pd.Timestamp
    common_calendar: pd.DatetimeIndex
    universe_id: str
    calendar_id: str


@dataclass(frozen=True, kw_only=True)
class StockPackets:
    request: inputs.InputRequest
    canonical: inputs.CanonicalPacket
    raw: inputs.RawQuotePacket
    intervals: inputs.IntervalPacket
    limits: inputs.OfficialLimitsPacket | None = None


@dataclass(frozen=True, kw_only=True)
class ComparisonSummary:
    cell_id: str
    primary: bool
    set_id: str
    band_id: str
    label: tuple[int, float]
    cadence: str
    era: str
    rates: Mapping[str, float | None]


@dataclass(frozen=True, kw_only=True)
class StudyAssembly:
    """All engineering outputs; metadata consistency is not source/PIT proof.

    Counts and diagnostics retain every explicit stock/year row. Summary stock
    sets are ID unions, and empty comparisons and null intervals remain present.
    Mapping views are immutable; borrowed input arrays must remain unchanged
    while assembly runs, as required by the staging contract.
    """

    rows: tuple[entry.CountRow, ...]
    diagnostics: tuple[entry.DiagnosticRow, ...]
    summaries: Mapping[entry.SummaryKey, entry.Summary]
    comparisons: tuple[ComparisonSummary, ...]
    intervals: tuple[bootstrap.IntervalRow, ...]
    axes: Mapping[str, bootstrap.CountAxes]
    alignment_records: Mapping[str, Mapping[str, str | int | None]]


def _axes(request: AssemblyRequest) -> dict[str, bootstrap.CountAxes]:
    if not isinstance(request, AssemblyRequest):
        raise ValueError("explicit AssemblyRequest required")
    for field in ("generation", "universe_id", "calendar_id"):
        value = getattr(request, field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"request.{field} must be an explicit nonempty string")
    as_of = request.study_as_of
    if not isinstance(as_of, pd.Timestamp) or pd.isna(as_of) or as_of.tz is not None or as_of != as_of.normalize():
        raise ValueError("request.study_as_of must be a normalized timezone-naive Timestamp without NaT")
    calendar = request.common_calendar
    if not isinstance(calendar, pd.DatetimeIndex) or calendar.tz is not None or calendar.hasnans:
        raise ValueError("request.common_calendar must be an explicit timezone-naive DatetimeIndex without NaT")
    if not calendar.is_unique or not calendar.is_monotonic_increasing or not calendar.equals(pd.DatetimeIndex(pd.Series(calendar).dt.normalize())):
        raise ValueError("request.common_calendar must contain unique increasing normalized session dates")
    years = tuple(sorted({int(year) for year in canonical.calendar_years(calendar)}))
    era_years = {
        "all": years,
        "2010-2012": tuple(year for year in years if 2010 <= year <= 2012),
        "2013-2018": tuple(year for year in years if 2013 <= year <= 2018),
        "2019+": tuple(year for year in years if year >= 2019),
    }
    result = {}
    for era in entry.ERAS:
        if not era_years[era]:
            raise ValueError(f"common calendar must provide a nonempty year axis for era {era}; years are never fabricated")
        result[era] = bootstrap.CountAxes(request.codes, era_years[era], era)
    return result


def _inventory(request: AssemblyRequest, packets: Iterable[StockPackets]) -> dict[str, StockPackets]:
    result = {}
    for bundle in packets:
        if not isinstance(bundle, StockPackets) or not isinstance(bundle.request, inputs.InputRequest):
            raise ValueError("explicit StockPackets and InputRequest required")
        stock_request = bundle.request
        code = stock_request.security_id
        if not isinstance(code, str) or code not in request.codes:
            raise ValueError("packet stock is outside the explicit request codes")
        if code in result:
            raise ValueError("duplicate stock packet bundle")
        for field in ("generation", "study_as_of", "universe_id", "calendar_id"):
            if getattr(stock_request, field) != getattr(request, field):
                raise ValueError(f"stock request.{field} differs from the common assembly request")
        if not isinstance(stock_request.common_calendar, pd.DatetimeIndex) or not stock_request.common_calendar.equals(request.common_calendar):
            raise ValueError("stock request.common_calendar differs from the common assembly calendar at original positions")
        for name, expected in (("canonical", inputs.CanonicalPacket), ("raw", inputs.RawQuotePacket), ("intervals", inputs.IntervalPacket)):
            if not isinstance(getattr(bundle, name), expected):
                raise ValueError(f"explicit {expected.__name__} required for {name}")
        if bundle.limits is not None and not isinstance(bundle.limits, inputs.OfficialLimitsPacket):
            raise ValueError("limits must be an explicit OfficialLimitsPacket or None")
        result[code] = bundle
    if set(result) != set(request.codes):
        raise ValueError("missing stock packet bundle; every explicit request code is required")
    return result


def assemble_study(request: AssemblyRequest, packets: Iterable[StockPackets], *, reps: int = 2000) -> StudyAssembly:
    """Validate all bundles, count full histories, and retain the fixed matrix.

    All stocks pass staging before the first count. Deterministic output order
    is sorted request codes for stock rows, then era/cell/cadence for comparisons
    and era/cell/cadence/method/statistic for intervals. One paired-weight object
    per era/method is reused across all cells and both cadences. Four era year
    axes come from the complete common calendar, never observed events.

    Default resampling is the preregistered 2,000 replicates. Smaller values are
    intended for synthetic engineering verification, not market evaluation.
    """
    if type(reps) is not int or reps < 1:
        raise ValueError("reps must be a positive Python integer")
    axes = _axes(request)
    inventory = _inventory(request, packets)
    staged: dict[str, inputs.StagedInputs] = {}
    for code in request.codes:
        bundle = inventory[code]
        staged[code] = inputs.stage_stock_inputs(bundle.request, canonical=bundle.canonical, raw=bundle.raw, intervals=bundle.intervals, limits=bundle.limits)
    LOGGER.debug("Validated entry-window packets: stocks=%s sessions=%s", len(staged), len(request.common_calendar))

    rows: list[entry.CountRow] = []
    diagnostics: list[entry.DiagnosticRow] = []
    for code in request.codes:
        stock = staged[code]
        counts = entry.count_stock(stock.calendar, stock.stock, stock.quotes)
        rows.extend(counts.rows)
        diagnostics.extend(counts.diagnostics)
    summaries = entry.aggregate_rows(rows)
    # Retain references rather than rescanning all stock/year rows for each cell.
    index: dict[tuple[str, str, str | None, tuple[int, float]], list[entry.CountRow]] = {}
    for row in rows:
        if row.arm == "M" or row.arm in entry.ARMS:
            index.setdefault((row.set_id, row.cadence, row.band_id, row.label), []).append(row)

    comparisons: list[ComparisonSummary] = []
    intervals: list[bootstrap.IntervalRow] = []
    for era in entry.ERAS:
        era_axes = axes[era]
        years = frozenset(era_axes.years)
        weights = {method: bootstrap.paired_weights(era_axes, method=method, reps=reps) for method in METHODS}
        for cell in entry.COMPARISONS:
            for cadence in entry.CADENCES:
                selected = chain(index[(cell.set_id, cadence, None, cell.label)], index[(cell.set_id, cadence, cell.band_id, cell.label)])
                cube = bootstrap.build_cell_cube((row for row in selected if row.t0_year in years), axes=era_axes, cell=cell, cadence=cadence)
                rates = entry.comparison_rates(summaries, cell, cadence, era)
                comparisons.append(
                    ComparisonSummary(
                        cell_id=cell.cell_id,
                        primary=cell.primary,
                        set_id=cell.set_id,
                        band_id=cell.band_id,
                        label=cell.label,
                        cadence=cadence,
                        era=era,
                        rates=MappingProxyType(rates),
                    )
                )
                for method in METHODS:
                    intervals.extend(bootstrap.bootstrap_cell(cube, weights[method]))
        LOGGER.debug("Assembled entry-window era=%s years=%s cells=%s", era, len(years), len(entry.COMPARISONS) * len(entry.CADENCES))
    return StudyAssembly(
        rows=tuple(rows),
        diagnostics=tuple(diagnostics),
        summaries=MappingProxyType(summaries),
        comparisons=tuple(comparisons),
        intervals=tuple(intervals),
        axes=MappingProxyType(axes),
        alignment_records=MappingProxyType({code: staged[code].alignment_record for code in request.codes}),
    )

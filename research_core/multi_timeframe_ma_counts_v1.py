"""Pure S7 per-stock counts: full-history S6 cooldown, then one common M.

Inputs are explicit saved states and canonical StockDaily labels. No signal or
outcome construction, data loading, aggregation, rates or research verdict lives
here. Source/PIT, historical assembly and market admission remain upstream gates.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from research_core import momentum_only_v1 as canonical

LOGGER = logging.getLogger(__name__)
DEFINITION_ID = "multi-timeframe-ma-counts.v1"
CANDIDATES = ("weekly-turn", "cross50", "cross70", "dense")
GROUPS = (*CANDIDATES, "C-base", "CORE")
CADENCES = ("daily", "cooled")
LABELS = tuple(label for label in canonical.LABELS if label[0] in (252, 504))
YEARS = tuple(range(2010, 2027))
METRICS = (*canonical.METRICS, "censored_unknown_n", "censored_observed_hit_n", "excluded_known_n", "quality_unknown_n")
COVERAGE_METRICS = ("S6_n", "M_n", "total_excluded_n")
STATE_METRICS = ("true_n", "false_n", "unknown_n")
MEMBERSHIP_METRICS = ("raw_s6_n", "retained_n", "admitted_n")
_MAX_ROWS = int(np.iinfo(np.int32).max)
_METRIC = {name: i for i, name in enumerate(METRICS)}


@dataclass(frozen=True, eq=False)
class StockCounts:
    security_id: str
    counts: NDArray[np.int64]
    coverage_counts: NDArray[np.int64]
    state_counts: NDArray[np.int64]
    membership_counts: NDArray[np.int64]
    groups: tuple[str, ...] = GROUPS
    cadences: tuple[str, ...] = CADENCES
    labels: tuple[tuple[int, float], ...] = LABELS
    years: tuple[int, ...] = YEARS
    metrics: tuple[str, ...] = METRICS
    coverage_metrics: tuple[str, ...] = COVERAGE_METRICS
    state_metrics: tuple[str, ...] = STATE_METRICS
    membership_metrics: tuple[str, ...] = MEMBERSHIP_METRICS


def _vector(values: np.ndarray, n: int, name: str, dtype: str, allowed: tuple[int, ...] | None = None) -> None:
    if type(values) is not np.ndarray or values.ndim != 1 or len(values) != n or values.dtype != np.dtype(dtype):
        raise ValueError(f"{name} must be a one-dimensional exact {dtype} ndarray of calendar length")
    if allowed is not None and not np.isin(values, allowed).all():
        raise ValueError(f"{name} contains an invalid state")


def _keys(values: Mapping, expected: tuple, name: str) -> None:
    if not isinstance(values, Mapping) or set(values) != set(expected):
        raise ValueError(f"{name} must contain exactly the required canonical keys")


def _calendar(calendar: pd.DatetimeIndex) -> NDArray[np.intp]:
    if not isinstance(calendar, pd.DatetimeIndex) or calendar.tz is not None or calendar.hasnans:
        raise ValueError("calendar must be a timezone-naive DatetimeIndex without NaT")
    if len(calendar) > _MAX_ROWS:
        raise ValueError("calendar length exceeds canonical int32 count capacity")
    if not calendar.is_unique or not calendar.is_monotonic_increasing or any(day != day.normalize() for day in calendar):
        raise ValueError("calendar must have unique increasing normalized session dates")
    years = canonical.calendar_years(calendar)
    if np.any((years < YEARS[0]) | (years > YEARS[-1])):
        raise ValueError("calendar years must be within 2010..2026")
    return (years - YEARS[0]).astype(np.intp)


def _year_counts(year_index: NDArray[np.intp], mask: NDArray[np.bool_]) -> NDArray[np.int64]:
    return np.bincount(year_index[mask], minlength=len(YEARS)).astype(np.int64)


def _readonly(values: NDArray[np.int64]) -> NDArray[np.int64]:
    return np.frombuffer(values.tobytes(), dtype=np.int64).reshape(values.shape)


def _error(stock: canonical.StockDaily, group: str, cadence: str, label: tuple[int, float], year: int, detail: str) -> ValueError:
    return ValueError(f"code={stock.code} group={group} cadence={cadence} label={label} year={year}: {detail}")


def _diagnostics(
    stock: canonical.StockDaily,
    admitted: NDArray[np.bool_],
    quality: NDArray[np.bool_],
    year_index: NDArray[np.intp],
    *,
    group: str,
    cadence: str,
    label: tuple[int, float],
) -> tuple[NDArray[np.int64], NDArray[np.int64]]:
    full = stock.calendar_full[label[0]]
    effective_label = np.where(quality, np.int8(0), stock.labels[label])
    effective_main = stock.main_eligible[label] & ~quality
    excluded = admitted & full & (effective_label != 0) & ~effective_main
    invalid = admitted & ((effective_main & ((effective_label == 0) | ~full)) | (~full & np.isin(effective_label, (2, 3))))
    bad = excluded | invalid
    if bad.any():
        year = int(year_index[np.flatnonzero(bad)[0]])
        within_year = year_index == year
        raise _error(
            stock,
            group,
            cadence,
            label,
            YEARS[year],
            f"excluded_known_n={int(np.count_nonzero(excluded & within_year))}; inconsistent_overlay_n={int(np.count_nonzero(invalid & within_year))}",
        )
    return _year_counts(year_index, admitted & ~full & (effective_label == 1)), _year_counts(year_index, admitted & quality)


def _partitions(stock: canonical.StockDaily, values: NDArray[np.int64], admitted_n: NDArray[np.int64], *, group: str, cadence: str) -> None:
    def column(name: str) -> NDArray[np.int64]:
        return values[:, :, _METRIC[name]]

    bad = (
        (column("known_n") != column("hit_n") + column("loss_n") + column("flat_win_n"))
        | (column("event_n") != column("known_n") + column("full_unknown_n") + column("censored_n"))
        | (column("unknown_n") != column("full_unknown_n") + column("censored_unknown_n"))
        | (column("event_n") != admitted_n[None, :])
        | (values < 0).any(axis=2)
    )
    if bad.any():
        li, yi = np.argwhere(bad)[0]
        raise _error(stock, group, cadence, LABELS[int(li)], YEARS[int(yi)], "excluded_known_n=0; canonical partition/admission mismatch")


def count_stock(
    stock: canonical.StockDaily,
    *,
    calendar: pd.DatetimeIndex,
    candidate_states: Mapping[str, np.ndarray],
    common_mask: np.ndarray,
) -> StockCounts:
    """Return fixed axes and int64 counts without changing or aliasing inputs.

    Every accessed label/main/full vector, including H126 required internally by
    public group_counts, must be supplied. Only H252/H504 labels are returned.
    Semantic partition checks concern admitted S7 events after quality overlay.
    """
    if not isinstance(stock, canonical.StockDaily) or not isinstance(stock.code, str) or not stock.code.strip() or stock.code != stock.code.strip():
        raise ValueError("stock must be StockDaily with a nonempty unpadded code")
    year_index = _calendar(calendar)
    n = len(calendar)
    _vector(stock.eligible, n, "eligible", "bool")
    _vector(stock.jump, n, "jump", "bool")
    _vector(common_mask, n, "common_mask", "bool")
    if np.any(common_mask & ~stock.eligible):
        raise ValueError("common_mask must be a subset of stock.eligible (S6)")
    _keys(candidate_states, CANDIDATES, "candidate_states")
    for name in CANDIDATES:
        _vector(candidate_states[name], n, name, "int8", (-1, 0, 1))
    _keys(stock.labels, canonical.LABELS, "labels")
    _keys(stock.main_eligible, canonical.LABELS, "main_eligible")
    _keys(stock.calendar_full, canonical.HORIZONS, "calendar_full")
    for label in canonical.LABELS:
        _vector(stock.labels[label], n, f"labels[{label}]", "int8", (0, 1, 2, 3))
        _vector(stock.main_eligible[label], n, f"main_eligible[{label}]", "bool")
    for horizon in canonical.HORIZONS:
        _vector(stock.calendar_full[horizon], n, f"calendar_full[{horizon}]", "bool")
    core_names = canonical.condition_sets()["A1&A2"]
    if not isinstance(stock.atoms, Mapping) or any(name not in stock.atoms for name in core_names):
        raise ValueError("stock.atoms must provide every canonical CORE atom")
    atoms = {name: stock.atoms[name] for name in core_names}
    for name, states in atoms.items():
        _vector(states, n, f"atoms[{name}]", "int8", (-1, 0, 1))
    members = {name: candidate_states[name] == 1 for name in CANDIDATES}
    members["C-base"] = np.ones(n, dtype=np.bool_)
    members["CORE"] = canonical.set_members(atoms, core_names)
    states_by_group = {
        **candidate_states,
        "C-base": np.ones(n, dtype=np.int8),
        "CORE": canonical.set_states(atoms, core_names, stock.eligible),
    }
    lookback = canonical.groups()["C-base-daily"][1]
    quality = {h: canonical.quality_unknown(stock.jump, lookback, h) for h in (252, 504)}
    counts = np.zeros((len(GROUPS), len(CADENCES), len(LABELS), len(YEARS), len(METRICS)), dtype=np.int64)
    coverage = np.zeros((len(YEARS), len(COVERAGE_METRICS)), dtype=np.int64)
    coverage[:, 0] = _year_counts(year_index, stock.eligible)
    coverage[:, 1] = _year_counts(year_index, common_mask)
    coverage[:, 2] = coverage[:, 0] - coverage[:, 1]
    state_counts = np.zeros((len(GROUPS), len(YEARS), len(STATE_METRICS)), dtype=np.int64)
    membership = np.zeros((len(GROUPS), len(CADENCES), len(YEARS), len(MEMBERSHIP_METRICS)), dtype=np.int64)
    for gi, group in enumerate(GROUPS):
        raw_s6 = members[group] & stock.eligible
        for si, state in enumerate((1, 0, -1)):
            state_counts[gi, :, si] = _year_counts(year_index, stock.eligible & (states_by_group[group] == state))
        for ci, cadence in enumerate(CADENCES):
            retained = raw_s6 if cadence == "daily" else canonical.cooled(members[group], stock.eligible)
            admitted = retained & common_mask
            membership[gi, ci, :, 0] = _year_counts(year_index, raw_s6)
            membership[gi, ci, :, 1] = _year_counts(year_index, retained)
            membership[gi, ci, :, 2] = _year_counts(year_index, admitted)
            base = canonical.group_counts(stock, admitted, lookback=lookback, year_index=year_index, n_years=len(YEARS)).astype(np.int64)
            for li, label in enumerate(LABELS):
                cell = counts[gi, ci, li]
                cell[:, : len(canonical.METRICS)] = base[canonical.LABELS.index(label)]
                observed_hit, quality_unknown = _diagnostics(
                    stock,
                    admitted,
                    quality[label[0]],
                    year_index,
                    group=group,
                    cadence=cadence,
                    label=label,
                )
                cell[:, _METRIC["censored_unknown_n"]] = cell[:, _METRIC["unknown_n"]] - cell[:, _METRIC["full_unknown_n"]]
                cell[:, _METRIC["censored_observed_hit_n"]] = observed_hit
                cell[:, _METRIC["quality_unknown_n"]] = quality_unknown
            _partitions(stock, counts[gi, ci], membership[gi, ci, :, 2], group=group, cadence=cadence)
    if not np.array_equal(state_counts.sum(axis=2), np.broadcast_to(coverage[:, 0], (len(GROUPS), len(YEARS)))):
        raise ValueError(f"code={stock.code}: S6 state audit does not partition")
    LOGGER.debug("S7 stock counts code=%s sessions=%d S6=%d M=%d", stock.code, n, int(stock.eligible.sum()), int(common_mask.sum()))
    return StockCounts(stock.code, _readonly(counts), _readonly(coverage), _readonly(state_counts), _readonly(membership))

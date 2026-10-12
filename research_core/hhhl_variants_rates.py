"""Incremental event counts and fixed-year diagnostics for HHHL variants v1.

No market data are read and no event records are retained. Distinct securities
are unioned across years, while all rates continue to describe events.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from numbers import Integral, Real
from typing import Any

LOGGER = logging.getLogger(__name__)
YEARS = tuple(range(2019, 2027))
_CORE_COUNTS = (
    "calendar_full_n",
    "hit_n",
    "loss_n",
    "flat_win_n",
    "unknown_n",
    "censored_n",
    "censored_hit_n",
    "censored_unknown_n",
)
_DERIVED_FIELDS = frozenset((
    "base_row_kind",
    "year",
    "removed_year",
    "known_security_n",
    "known_n",
    "hit_rate",
    "loss_rate",
    "hit_lower",
    "hit_upper",
    "loss_lower",
    "loss_upper",
    "censored_hit_lower",
    "censored_hit_upper",
    "small_sample",
))


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _count(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")
    return int(value)


@dataclass
class _YearCounts:
    counts: Counter[str] = field(default_factory=Counter)
    known_codes: set[str] = field(default_factory=set)


@dataclass
class _Group:
    metadata: dict[str, Any]
    years: dict[int, _YearCounts] = field(default_factory=dict)
    count_names: set[str] = field(default_factory=lambda: set(_CORE_COUNTS))


class RateAccumulator:
    """Aggregate additive counts by caller-defined key and t0 calendar year."""

    def __init__(self) -> None:
        self._groups: dict[tuple[Any, ...], _Group] = {}

    def add(
        self,
        key: tuple[Any, ...],
        metadata: dict[str, Any],
        year: int,
        counts: dict[str, int],
        known_codes: Iterable[str] = (),
    ) -> None:
        """Validate a single batch before mutating any accumulated state."""
        if not isinstance(key, tuple):
            raise ValueError("key must be a hashable tuple")
        try:
            hash(key)
        except TypeError as error:
            raise ValueError("key must be a hashable tuple") from error
        if isinstance(year, bool) or not isinstance(year, Integral) or year not in YEARS:
            raise ValueError("year must be in 2019..2026")
        if not isinstance(metadata, dict) or not isinstance(metadata.get("row_kind"), str) or not metadata["row_kind"]:
            raise ValueError("metadata must include a nonempty row_kind")
        if metadata["row_kind"] in {"year", "drop_best_year"}:
            raise ValueError("row_kind is reserved for derived rows")
        if _DERIVED_FIELDS.intersection(metadata) or set(_CORE_COUNTS).intersection(metadata):
            raise ValueError("metadata cannot override counts or derived fields")
        clean_counts: dict[str, int] = {}
        for name, value in counts.items():
            if not isinstance(name, str) or not name.endswith("_n") or name in _DERIVED_FIELDS or name in metadata:
                raise ValueError(f"invalid additive count name: {name!r}")
            clean_counts[name] = _count(value, name)
        for name in _CORE_COUNTS:
            clean_counts.setdefault(name, 0)
        if sum(clean_counts[name] for name in ("hit_n", "loss_n", "flat_win_n", "unknown_n")) != clean_counts["calendar_full_n"]:
            raise ValueError("full-window labels must partition calendar_full_n")
        if clean_counts["censored_hit_n"] + clean_counts["censored_unknown_n"] != clean_counts["censored_n"]:
            raise ValueError("censored labels must partition censored_n")
        codes = set(known_codes)
        if any(not isinstance(code, str) or not code.strip() for code in codes):
            raise ValueError("known_codes must contain nonempty original string codes")
        known = clean_counts["hit_n"] + clean_counts["loss_n"] + clean_counts["flat_win_n"]
        if len(codes) > known:
            raise ValueError("known security count cannot exceed known events")
        group = self._groups.get(key)
        if group is not None and group.metadata != metadata:
            raise ValueError("inconsistent metadata for repeated key")
        if group is None:
            group = _Group(deepcopy(metadata))
            self._groups[key] = group
        group.count_names.update(clean_counts)
        bucket = group.years.setdefault(int(year), _YearCounts())
        bucket.counts.update(clean_counts)
        bucket.known_codes.update(codes)

    @staticmethod
    def _row(group: _Group, years: Iterable[int], row_kind: str, *, year: int | None = None, removed_year: int | None = None) -> dict[str, Any]:
        counts: Counter[str] = Counter()
        codes: set[str] = set()
        for included_year in years:
            bucket = group.years.get(included_year)
            if bucket is not None:
                counts.update(bucket.counts)
                codes.update(bucket.known_codes)
        row = deepcopy(group.metadata)
        row.update({name: counts[name] for name in sorted(group.count_names)})
        known = counts["hit_n"] + counts["loss_n"] + counts["flat_win_n"]
        full = counts["calendar_full_n"]
        censored = counts["censored_n"]
        row.update(
            row_kind=row_kind,
            base_row_kind=group.metadata["row_kind"],
            year=year,
            removed_year=removed_year,
            known_n=known,
            known_security_n=len(codes),
            hit_rate=_ratio(counts["hit_n"], known),
            loss_rate=_ratio(counts["loss_n"], known),
            hit_lower=_ratio(counts["hit_n"], full),
            hit_upper=_ratio(counts["hit_n"] + counts["unknown_n"], full),
            loss_lower=_ratio(counts["loss_n"], full),
            loss_upper=_ratio(counts["loss_n"] + counts["unknown_n"], full),
            censored_hit_lower=_ratio(counts["censored_hit_n"], censored),
            censored_hit_upper=_ratio(counts["censored_hit_n"] + counts["censored_unknown_n"], censored),
            small_sample=known < 300,
        )
        return row

    def finalize(self) -> list[dict[str, Any]]:
        """Emit one pooled, eight fixed-year and one sensitivity row per key."""
        rows: list[dict[str, Any]] = []
        for group in self._groups.values():
            rows.append(self._row(group, YEARS, group.metadata["row_kind"]))
            rows.extend(self._row(group, (year,), "year", year=year) for year in YEARS)
            event_years = [year for year, bucket in group.years.items() if bucket.counts["calendar_full_n"] + bucket.counts["censored_n"] > 0]
            best_year = min(event_years, key=lambda year: (-group.years[year].counts["hit_n"], year)) if event_years else None
            rows.append(self._row(group, (year for year in YEARS if year != best_year), "drop_best_year", removed_year=best_year))
        LOGGER.debug("Finalized %d rate groups into %d rows", len(self._groups), len(rows))
        return rows


def descriptive_flag_rates(triggered: int, all_false: int, unknown: int) -> dict[str, int | float | None]:
    """Separate the observed flag denominator from full-population bounds."""
    triggered, all_false, unknown = (_count(value, name) for value, name in ((triggered, "triggered"), (all_false, "all_false"), (unknown, "unknown")))
    known = triggered + all_false
    total = known + unknown
    return {
        "triggered_n": triggered,
        "all_false_n": all_false,
        "unknown_n": unknown,
        "known_n": known,
        "known_rate": _ratio(triggered, known),
        "all_n": total,
        "lower": _ratio(triggered, total),
        "upper": _ratio(triggered + unknown, total),
    }


def trigger_return_summary(values: Iterable[float | int | None]) -> dict[str, int | float | None]:
    """Linear p10/median/p90 over finite returns; invalid values remain unknown."""
    finite: list[float] = []
    unknown = 0
    for value in values:
        if isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value)):
            finite.append(float(value))
        else:
            unknown += 1
    finite.sort()

    def quantile(probability: float) -> float | None:
        if not finite:
            return None
        position = (len(finite) - 1) * probability
        lower = math.floor(position)
        upper = math.ceil(position)
        weight = position - lower
        return finite[lower] * (1 - weight) + finite[upper] * weight

    return {
        "trigger_return_n": len(finite),
        "trigger_return_unknown_n": unknown,
        "trigger_return_p10": quantile(0.1),
        "trigger_return_median": quantile(0.5),
        "trigger_return_p90": quantile(0.9),
    }

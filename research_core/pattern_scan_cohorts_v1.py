"""Independent subtype and union event cohorts for one stock and pattern."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from research_core.pattern_scan_events_v1 import per_group_cooldown

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SubtypeCohort:
    subtype_id: str
    retained_indices: tuple[int, ...]


@dataclass(frozen=True)
class PatternCohorts:
    subtype_cohorts: tuple[SubtypeCohort, ...]
    union_indices: tuple[int, ...]


def build_pattern_cohorts(candidates: Mapping[str, Iterable[int]]) -> PatternCohorts:
    """Apply independent 20-session cooldowns to raw subtype and union events.

    Supply candidates for exactly one stock and pattern on one common calendar.
    Subtype identifiers are nonblank strings preserved verbatim. Empty subtypes
    remain present, and subtype order is lexical. Each iterable is consumed once;
    union candidates come from every raw index, including subtype-suppressed
    indices. The existing public cooldown primitive validates session indices and
    deduplicates same-day union events. No retained cohort filters another.
    """
    for subtype_id in candidates:
        if not isinstance(subtype_id, str) or not subtype_id.strip():
            raise ValueError("subtype identifiers must be nonblank strings")
    cohorts: list[SubtypeCohort] = []
    union_raw: list[int] = []
    for subtype_id in sorted(candidates):
        raw = tuple(candidates[subtype_id])
        cohorts.append(SubtypeCohort(subtype_id, per_group_cooldown(raw)))
        union_raw.extend(raw)
    union = per_group_cooldown(union_raw)
    log.debug("Built %d independent subtype cohorts and %d union events", len(cohorts), len(union))
    return PatternCohorts(tuple(cohorts), union)

"""Pattern-scan v1 development-only selection (handoff section 5.3).

Callers supply one pattern's original union events and explicit target cohorts.
Confirmation reporting retains every candidate, including empty intersections.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from fractions import Fraction
from itertools import combinations
from urllib.parse import quote

from research_core.hhhl_variants_selection import (
    Atom,
    Candidate,
    DevelopmentCounts,
    SelectionEvent,
    SelectionResult,
    candidate_id,
    split_for_code,
)

LOGGER = logging.getLogger(__name__)
_KNOWN = frozenset(("hit", "loss", "flat-win"))
_MISSING = frozenset(("unknown", "not_applicable", "feature_unknown", "warmup_insufficient"))


def _key(atom: Atom) -> tuple[str, str]:
    return atom.feature_id, atom.bin_id


def _counts(rows: Iterable[SelectionEvent]) -> DevelopmentCounts:
    events = tuple(rows)
    return DevelopmentCounts(
        sum(row.label == "hit" for row in events),
        sum(row.label == "loss" for row in events),
        sum(row.label == "flat-win" for row in events),
        len({row.code for row in events}),
    )


def select_pattern_candidates(
    pattern_id: str,
    events: Iterable[SelectionEvent],
    atoms: Iterable[Atom],
    *,
    target_cohorts: Iterable[str],
) -> SelectionResult:
    """Select up to eight family-distinct singles and all pairs/triples.

    Singles require at least 100 known events and 30 distinct stock codes.
    Counts use CRC development, H126, full-calendar known events exclusively.
    Pattern isolation is the caller's responsibility; duplicated event/horizon
    identities fail even across union/subtype cohorts or excluded rows.
    DevelopmentCounts.small_known retains its legacy 300-row diagnostic meaning;
    it is not this selector's eligibility gate.
    """
    if not isinstance(pattern_id, str) or not pattern_id.strip():
        raise ValueError("pattern_id must be a nonempty string")
    if isinstance(target_cohorts, str):
        raise ValueError("target_cohorts must be an iterable of cohort strings")
    cohorts = frozenset(target_cohorts)
    if not cohorts or any(not isinstance(cohort, str) or not cohort.strip() for cohort in cohorts):
        raise ValueError("target_cohorts must contain nonempty strings")
    inventory: dict[tuple[str, str], Atom] = {}
    families: dict[str, str] = {}
    for atom in atoms:
        if _key(atom) in inventory:
            raise ValueError("duplicate inventory atom")
        if atom.feature_id in families and families[atom.feature_id] != atom.family:
            raise ValueError("feature has inconsistent resolved families")
        inventory[_key(atom)] = atom
        families[atom.feature_id] = atom.family
    seen: set[tuple[str, int]] = set()
    rows: list[SelectionEvent] = []
    for row in events:
        identity = row.event_id, row.horizon
        if identity in seen:
            raise ValueError(f"duplicate event identity: {identity!r}")
        seen.add(identity)
        if any(inventory.get(_key(atom)) != atom for atom in row.atoms):
            raise ValueError("event atom absent or inconsistent with inventory")
        if len({atom.feature_id for atom in row.atoms}) != len(row.atoms):
            raise ValueError("event has multiple bins for one feature")
        if row.cohort_id in cohorts and split_for_code(row.code) == "development" and row.horizon == 126 and row.calendar_full and row.label in _KNOWN:
            rows.append(row)
    ranked: list[tuple[Atom, DevelopmentCounts]] = []
    for atom in inventory.values():
        if not atom.selectable or atom.family == "K" or atom.bin_id in _MISSING:
            continue
        counts = _counts(row for row in rows if atom in row.atoms)
        if counts.known >= 100 and counts.distinct_codes >= 30:
            ranked.append((atom, counts))
    ranked.sort(key=lambda item: (-Fraction(item[1].hit, item[1].known), *_key(item[0])))
    selected: list[Atom] = []
    used: set[str] = set()
    for atom, _ in ranked:
        if atom.family not in used:
            selected.append(atom)
            used.add(atom.family)
            if len(selected) == 8:
                break
    candidates: list[Candidate] = []
    for size in (1, 2, 3):
        for members in combinations(selected, size):
            ordered = tuple(sorted(members, key=_key))
            # Reuse the public canonical feature/bin encoding, not its HHHL namespace.
            encoded = candidate_id(ordered).partition(":")[2]
            identifier = f"pattern-scan.v1:{quote(pattern_id, safe='')}:{encoded}"
            counts = _counts(row for row in rows if all(atom in row.atoms for atom in ordered))
            candidates.append(Candidate(identifier, ordered, counts))
    LOGGER.info(
        "Pattern scan %s: development_known=%d eligible=%d selected=%d candidates=%d",
        pattern_id,
        len(rows),
        len(ranked),
        len(selected),
        len(candidates),
    )
    return SelectionResult(tuple(selected), tuple(candidates), _counts(rows))

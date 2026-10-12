"""Pure, deterministic development-half selection for HHHL v4 variants v1.

Feature definitions and market data remain with the caller. Counts describe
original events in the P-clean/P-over union, never a strategy verdict.
"""

from __future__ import annotations

import logging
import zlib
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from itertools import combinations
from urllib.parse import quote

LOGGER = logging.getLogger(__name__)
_KNOWN_LABELS = frozenset(("hit", "loss", "flat-win"))
_COHORTS = frozenset(("P-clean", "P-over"))
_EXCLUDED_BINS = frozenset(("unknown", "not_applicable", "feature_unknown", "warmup_insufficient"))


def _nonempty_string(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string")


@dataclass(frozen=True)
class Atom:
    """One resolved feature bin; caller marks all other missing reasons unselectable."""

    family: str
    feature_id: str
    bin_id: str
    selectable: bool = True

    def __post_init__(self) -> None:
        for name in ("family", "feature_id", "bin_id"):
            _nonempty_string(getattr(self, name), name)
        if type(self.selectable) is not bool:
            raise ValueError("selectable must be bool")


@dataclass(frozen=True)
class SelectionEvent:
    """An original stock event at one horizon, with resolved observed atoms."""

    event_id: str
    code: str
    cohort_id: str
    horizon: int
    calendar_full: bool
    label: str
    atoms: frozenset[Atom]

    def __post_init__(self) -> None:
        for name in ("event_id", "code", "cohort_id"):
            _nonempty_string(getattr(self, name), name)
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ValueError("horizon must be a positive integer")
        if type(self.calendar_full) is not bool:
            raise ValueError("calendar_full must be bool")
        if self.label not in _KNOWN_LABELS | {"unknown"}:
            raise ValueError(f"invalid label: {self.label!r}")
        object.__setattr__(self, "atoms", frozenset(self.atoms))
        if any(not isinstance(atom, Atom) for atom in self.atoms):
            raise ValueError("event atoms must contain Atom values")


@dataclass(frozen=True)
class DevelopmentCounts:
    hit: int
    loss: int
    flat_win: int
    distinct_codes: int

    @property
    def known(self) -> int:
        return self.hit + self.loss + self.flat_win

    @property
    def rate(self) -> Fraction | None:
        """None explicitly denotes an undefined rate with zero known events."""
        return Fraction(self.hit, self.known) if self.known else None

    @property
    def small_known(self) -> bool:
        return self.known < 300


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    atoms: tuple[Atom, ...]
    development_counts: DevelopmentCounts


@dataclass(frozen=True)
class SelectionResult:
    selected_atoms: tuple[Atom, ...]
    candidates: tuple[Candidate, ...]
    development_counts: DevelopmentCounts


def split_for_code(code: str) -> str:
    """Split the original UTF-8 string, preserving all leading zeros."""
    _nonempty_string(code, "code")
    return "development" if zlib.crc32(code.encode("utf-8")) % 2 == 0 else "cross-check"


def _atom_key(atom: Atom) -> tuple[str, str]:
    return atom.feature_id, atom.bin_id


def candidate_id(atoms: Iterable[Atom]) -> str:
    """Versioned identity from sorted feature/bin strings, independent of results."""
    ordered = sorted(atoms, key=_atom_key)
    if not ordered or len({_atom_key(atom) for atom in ordered}) != len(ordered):
        raise ValueError("candidate must have nonempty, unique feature/bin atoms")
    parts = (f"{quote(atom.feature_id, safe='')}={quote(atom.bin_id, safe='')}" for atom in ordered)
    return "hhhl-v4-variants.v1:" + "&".join(parts)


def _counts(events: Iterable[SelectionEvent]) -> DevelopmentCounts:
    rows = tuple(events)
    return DevelopmentCounts(
        hit=sum(row.label == "hit" for row in rows),
        loss=sum(row.label == "loss" for row in rows),
        flat_win=sum(row.label == "flat-win" for row in rows),
        distinct_codes=len({row.code for row in rows}),
    )


def _development_events(events: Iterable[SelectionEvent], inventory: dict[tuple[str, str], Atom]) -> tuple[SelectionEvent, ...]:
    seen: dict[tuple[str, int], SelectionEvent] = {}
    for row in events:
        key = row.event_id, row.horizon
        if key in seen:
            if seen[key].code != row.code:
                raise ValueError(f"inconsistent code for event identity: {key!r}")
            raise ValueError(f"duplicate event identity: {key!r}")
        seen[key] = row
        for atom in row.atoms:
            if inventory.get(_atom_key(atom)) != atom:
                raise ValueError(f"event atom absent or inconsistent with inventory: {atom!r}")
        if len({atom.feature_id for atom in row.atoms}) != len(row.atoms):
            raise ValueError("event has multiple bins for one feature")
    return tuple(
        row
        for row in seen.values()
        if row.cohort_id in _COHORTS and split_for_code(row.code) == "development" and row.horizon == 126 and row.calendar_full and row.label in _KNOWN_LABELS
    )


def select_candidates(events: Iterable[SelectionEvent], atoms: Iterable[Atom]) -> SelectionResult:
    """Select at most five family-distinct singles, all pairs, and one triple.

    Singles require 300 known events and 60 distinct development stock codes.
    Pair/triple counts have no sample gate. Target cohorts are mutually exclusive;
    repeated (event_id, horizon) identities are rejected, even across cohorts.
    """
    inventory: dict[tuple[str, str], Atom] = {}
    families: dict[str, str] = {}
    for atom in atoms:
        key = _atom_key(atom)
        if key in inventory:
            raise ValueError(f"duplicate inventory atom: {key!r}")
        if atom.feature_id in families and families[atom.feature_id] != atom.family:
            raise ValueError("feature has inconsistent resolved families")
        inventory[key] = atom
        families[atom.feature_id] = atom.family
    rows = _development_events(events, inventory)
    ranked: list[tuple[Atom, DevelopmentCounts]] = []
    for atom in inventory.values():
        if not atom.selectable or atom.family == "K" or atom.bin_id in _EXCLUDED_BINS:
            continue
        counts = _counts(row for row in rows if atom in row.atoms)
        if counts.known >= 300 and counts.distinct_codes >= 60:
            ranked.append((atom, counts))
    # Eligibility ensures every ranked rate is defined; use exact rational arithmetic.
    ranked.sort(key=lambda item: (-Fraction(item[1].hit, item[1].known), *_atom_key(item[0])))
    selected: list[Atom] = []
    used_families: set[str] = set()
    for atom, _ in ranked:
        if atom.family not in used_families:
            selected.append(atom)
            used_families.add(atom.family)
            if len(selected) == 5:
                break

    def make_candidate(members: Iterable[Atom]) -> Candidate:
        ordered = tuple(sorted(members, key=_atom_key))
        counts = _counts(row for row in rows if all(atom in row.atoms for atom in ordered))
        return Candidate(candidate_id(ordered), ordered, counts)

    singles = [make_candidate((atom,)) for atom in selected]
    pairs = [make_candidate(pair) for pair in combinations(selected, 2)]
    candidates = singles + pairs
    calculable = [pair for pair in pairs if pair.development_counts.known > 0]
    if calculable:
        best = min(
            calculable,
            key=lambda pair: (
                -Fraction(pair.development_counts.hit, pair.development_counts.known),
                pair.candidate_id,
            ),
        )
        remaining = next((atom for atom in selected if atom not in best.atoms), None)
        if remaining is not None:
            candidates.append(make_candidate((*best.atoms, remaining)))
    LOGGER.info("HHHL variants: development_known=%d eligible_atoms=%d selected=%d candidates=%d", len(rows), len(ranked), len(selected), len(candidates))
    return SelectionResult(tuple(selected), tuple(candidates), _counts(rows))

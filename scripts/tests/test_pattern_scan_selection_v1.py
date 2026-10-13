"""Hand-calculated synthetic selection fixtures; no market inputs."""

import zlib
from collections.abc import Iterable
from dataclasses import replace
from fractions import Fraction

import pytest

from research_core.hhhl_variants_selection import Atom, SelectionEvent, SelectionResult, split_for_code
from research_core.pattern_scan_selection_v1 import select_pattern_candidates


def codes(count: int = 30, split: str = "development") -> list[str]:
    return [f"{i:05}" for i in range(1000) if split_for_code(f"{i:05}") == split][:count]


def block(
    prefix: str,
    atoms: Iterable[Atom],
    known: int = 100,
    hits: int = 50,
    stock_codes: list[str] | None = None,
) -> list[SelectionEvent]:
    stock_codes = codes() if stock_codes is None else stock_codes
    return [
        SelectionEvent(
            f"{prefix}-{i}", stock_codes[i % len(stock_codes)], "union", 126, True, "hit" if i < hits else ("loss" if i % 2 else "flat-win"), frozenset(atoms)
        )
        for i in range(known)
    ]


def select(events: Iterable[SelectionEvent], atoms: Iterable[Atom], pattern: str = "R1") -> SelectionResult:
    return select_pattern_candidates(pattern, events, atoms, target_cohorts=("union",))


def test_confirmation_and_ineligible_rows_do_not_change_selection():
    a, b = Atom("A", "a", "high"), Atom("B", "b", "high")
    base = block("base", (a,), hits=40)
    extras = block("cross", (b,), 1000, 1000, codes(split="cross-check"))
    for prefix, changes in (
        ("unknown", {"label": "unknown"}),
        ("short", {"calendar_full": False}),
        ("h252", {"horizon": 252}),
        ("other", {"cohort_id": "another-pattern"}),
    ):
        extras += [replace(row, **changes) for row in block(prefix, (b,), hits=100)]
    result = select(base, (a, b))
    assert select(base + extras, (a, b)) == result
    assert result.development_counts.known == 100
    assert result.development_counts.rate == Fraction(2, 5)
    assert result.development_counts.loss == result.development_counts.flat_win == 30


def test_both_thresholds_and_no_relaxation():
    a, b, c = (Atom(x, x, "high") for x in "ABC")
    events = block("99", (a,), 99, 99) + block("29", (b,), stock_codes=codes(29)) + block("ok", (c,))
    result = select(events, (a, b, c))
    assert result.selected_atoms == (c,)
    assert len(result.candidates) == 1
    assert result.candidates[0].development_counts.known == 100
    assert result.candidates[0].development_counts.distinct_codes == 30


def test_eight_singles_generate_all_92_candidates_deterministically():
    atoms = tuple(Atom(x, x, "high") for x in "ABCDEFGHI")
    rows = block("all", atoms)
    result = select(rows, reversed(atoms))
    assert result.selected_atoms == atoms[:8]
    assert [sum(len(c.atoms) == size for c in result.candidates) for size in (1, 2, 3)] == [8, 28, 56]
    assert result == select(reversed(rows), atoms)
    assert len({c.candidate_id for c in result.candidates}) == 92
    assert all(c.candidate_id.startswith("pattern-scan.v1:R1:") for c in result.candidates)
    assert result.candidates[0].candidate_id != select(rows, atoms, "R2").candidates[0].candidate_id


def test_exact_fraction_ranking_and_one_per_family():
    a, b, c, d = Atom("A", "a", "high"), Atom("B", "b", "high"), Atom("A", "c", "high"), Atom("D", "d", "high")
    rows = block("a", (a,), hits=33) + block("b", (b,), 10001, 3301)
    rows += block("c", (c,), hits=33) + block("d", (d,), hits=33)
    result = select(rows, (d, c, b, a))
    assert result.selected_atoms == (b, a, d)
    assert result.candidates[0].development_counts.rate == Fraction(3301, 10001)


def test_empty_intersections_keep_all_pairs_and_triples_with_undefined_rate():
    atoms = tuple(Atom(x, x, "high") for x in "ABC")
    rows: list[SelectionEvent] = sum((block(x, (atom,)) for x, atom in zip("abc", atoms)), [])
    result = select(rows, atoms)
    assert len(result.candidates) == 7
    assert all(c.development_counts.rate is None for c in result.candidates if len(c.atoms) > 1)
    assert select([], atoms).development_counts.rate is None
    unknown = [replace(row, label="unknown") for row in rows]
    assert select(unknown, atoms).development_counts.rate is None
    assert not select(unknown, atoms).candidates


def test_k_missing_and_unselectable_diagnostics_excluded():
    atoms = (
        Atom("K", "K", "high"),
        Atom("A", "A", "unknown"),
        Atom("B", "B", "feature_unknown"),
        Atom("C", "C", "not_applicable"),
        Atom("D", "D", "warmup_insufficient"),
        Atom("E", "E", "other", False),
    )
    assert not select(block("all", atoms, hits=100), atoms).selected_atoms


def test_union_subtype_duplicates_fail_instead_of_double_counting():
    a = Atom("A", "a", "high")
    row = block("one", (a,), known=1)[0]
    for duplicate in (row, replace(row, cohort_id="subtype"), replace(row, code=codes()[1])):
        with pytest.raises(ValueError, match="duplicate event identity"):
            select((row, duplicate), (a,))
    assert select((row, replace(row, horizon=252)), (a,)).development_counts.known == 1


def test_crc_uses_original_leading_zero_code():
    code = next(f"{i:05}" for i in range(1000) if split_for_code(f"{i:05}") != split_for_code(str(i)))
    assert split_for_code(code) == ("development" if zlib.crc32(code.encode()) % 2 == 0 else "cross-check")
    a = Atom("A", "a", "high")
    row = block("crc", (a,), 1, stock_codes=[code])[0]
    assert select((row,), (a,)).development_counts.known == int(split_for_code(code) == "development")
    assert select((replace(row, code=str(int(code))),), (a,)).development_counts.known == int(split_for_code(code) != "development")


def test_inventory_validation_and_explicit_cohorts():
    a, low = Atom("A", "a", "high"), Atom("A", "a", "low")
    row = block("one", (a,), 1)[0]
    for atoms, rows, message in (
        ((a, a), (), "duplicate inventory"),
        ((a, Atom("B", "a", "low")), (), "inconsistent resolved families"),
        ((), (row,), "absent or inconsistent"),
        ((a, low), (replace(row, atoms=frozenset((a, low))),), "multiple bins"),
    ):
        with pytest.raises(ValueError, match=message):
            select(rows, atoms)
    for cohorts in ((), ("",), "union"):
        with pytest.raises(ValueError, match="target_cohorts"):
            select_pattern_candidates("R1", (), (), target_cohorts=cohorts)
    with pytest.raises(ValueError, match="pattern_id"):
        select((), (), " ")

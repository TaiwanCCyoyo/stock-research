"""Synthetic event fixtures only: no primary datasets or market calculations."""

import zlib
from dataclasses import replace
from fractions import Fraction

import pytest

from research_core.hhhl_variants_selection import (
    Atom,
    SelectionEvent,
    candidate_id,
    select_candidates,
    split_for_code,
)


def codes(split: str = "development", count: int = 60) -> list[str]:
    return [f"{index:05}" for index in range(1000) if split_for_code(f"{index:05}") == split][:count]


def block(prefix: str, atoms: tuple[Atom, ...], known: int = 300, hits: int = 200, stock_codes: list[str] | None = None) -> list[SelectionEvent]:
    stock_codes = codes() if stock_codes is None else stock_codes
    return [
        SelectionEvent(
            f"{prefix}-{index}",
            stock_codes[index % len(stock_codes)],
            "P-clean" if index % 2 == 0 else "P-over",
            126,
            True,
            "hit" if index < hits else ("loss" if index % 2 else "flat-win"),
            frozenset(atoms),
        )
        for index in range(known)
    ]


def test_crc_uses_original_utf8_code_and_preserves_leading_zero() -> None:
    for code in ("0050", "50", "台灣0050"):
        assert split_for_code(code) == ("development" if zlib.crc32(code.encode()) % 2 == 0 else "cross-check")
    index = next(index for index in range(1000) if zlib.crc32(f"{index:04}".encode()) % 2 != zlib.crc32(str(index).encode()) % 2)
    assert split_for_code(f"{index:04}") != split_for_code(str(index))
    for invalid_code in (50, "", " "):
        with pytest.raises(ValueError, match="nonempty string"):
            split_for_code(invalid_code)  # type: ignore[arg-type]


def test_excluded_events_cannot_change_selection_or_counts() -> None:
    a, b = Atom("B", "B", "high"), Atom("C", "C", "high")
    base = block("base", (a,))
    extras = block("cross", (b,), hits=300, stock_codes=codes("cross-check"))
    extras += [replace(row, event_id="incomplete-" + row.event_id, calendar_full=False) for row in block("full", (b,), hits=300)]
    extras += [replace(row, event_id="unknown-" + row.event_id, label="unknown") for row in block("label", (b,), hits=300)]
    extras += [replace(row, horizon=252) for row in block("long", (b,), hits=300)]
    extras += [replace(row, cohort_id="P-all") for row in block("other", (b,), hits=300)]
    assert select_candidates(base + extras, (a, b)) == select_candidates(base, (a, b))
    result = select_candidates(base, (a, b))
    assert result.development_counts.known == 300
    assert result.development_counts.distinct_codes == 60
    assert result.development_counts.loss + result.development_counts.flat_win == 100


def test_exact_fractions_that_round_identically_and_lexical_ties() -> None:
    a, b, c = (Atom(name, name, "high") for name in ("A", "B", "C"))
    # Both render as 0.333 at three decimals; B's exact rate is greater.
    result = select_candidates(block("a", (a,), hits=100) + block("b", (b,), known=3001, hits=1001) + block("c", (c,), hits=100), (c, a, b))
    assert result.selected_atoms == (b, a, c)
    assert result.candidates[0].development_counts.rate == Fraction(1001, 3001)
    assert select_candidates(reversed(block("tie", (a, c))), (c, a)).selected_atoms == (a, c)


def test_same_family_suppression_and_fewer_than_five() -> None:
    b, b2, c = Atom("B", "B", "high"), Atom("B", "B2", "high"), Atom("C", "C", "high")
    result = select_candidates(block("both", (b, b2, c)), (c, b2, b))
    assert result.selected_atoms == (b, c)
    assert len(result.candidates) == 3
    # Family supplied by inventory is authoritative, not a guessed prefix.
    other = Atom("OTHER", "B-looking", "high")
    assert len(select_candidates(block("other", (b, other)), (b, other)).selected_atoms) == 2


def test_single_gates_are_both_required_and_all_original_events_count() -> None:
    a, b, c = (Atom(name, name, "high") for name in ("A", "B", "C"))
    events = block("small", (a,), known=299, hits=299)
    events += block("few-codes", (b,), stock_codes=codes(count=59))
    events += block("valid", (c,))
    assert select_candidates(events, (a, b, c)).selected_atoms == (c,)
    # Multiple events per stock are kept; different stocks are independent rows.
    assert select_candidates(events, (a, b, c)).development_counts.known == 899


def test_disjoint_pairs_use_intersection_retain_zero_and_no_triple() -> None:
    a, b, c = (Atom(name, name, "high") for name in ("A", "B", "C"))
    result = select_candidates(block("a", (a,)) + block("b", (b,)) + block("c", (c,)), (a, b, c))
    pairs = [candidate for candidate in result.candidates if len(candidate.atoms) == 2]
    assert len(pairs) == 3
    assert all(pair.development_counts.known == 0 for pair in pairs)
    assert all(pair.development_counts.rate is None and pair.development_counts.small_known for pair in pairs)
    assert len(result.candidates) == 6


def test_best_pair_then_highest_ranked_absent_single_and_no_combo_gate() -> None:
    a, b, c, d = (Atom(name, name, "high") for name in ("A", "B", "C", "D"))
    events = block("a", (a,), hits=299) + block("b", (b,), hits=290)
    events += block("c", (c,), hits=280) + block("d", (d,), hits=270)
    events += block("cd", (c, d), known=1, hits=1)
    events += block("ab", (a, b), known=1, hits=0)
    result = select_candidates(events, (a, b, c, d))
    assert result.selected_atoms == (a, b, c, d)
    triple = result.candidates[-1]
    assert triple.atoms == (a, c, d)
    assert triple.development_counts.known == 0
    assert triple.development_counts.rate is None
    cd = next(item for item in result.candidates if item.atoms == (c, d))
    assert cd.development_counts.known == 1
    assert cd.development_counts.small_known


def test_max_sixteen_and_pair_tie_uses_canonical_id() -> None:
    atoms = tuple(Atom(name, name, "high") for name in "ABCDEF")
    events = block("all", atoms, hits=300)
    result = select_candidates(events, reversed(atoms))
    assert result.selected_atoms == atoms[:5]
    assert len(result.candidates) == 16
    assert result.candidates[-1].atoms == atoms[:3]
    assert result == select_candidates(reversed(events), atoms)
    changed = [replace(row, label="loss") for row in events]
    assert [item.candidate_id for item in result.candidates] == [item.candidate_id for item in select_candidates(changed, atoms).candidates]


def test_diagnostics_and_missing_bins_never_selectable() -> None:
    excluded = (
        Atom("K", "K", "high"),
        Atom("A", "A", "unknown"),
        Atom("B", "B", "not_applicable"),
        Atom("C", "C", "feature_unknown"),
        Atom("D", "D", "warmup_insufficient"),
        Atom("E", "E", "short_warmup", False),
    )
    assert not select_candidates(block("all", excluded, hits=300), excluded).selected_atoms
    assert select_candidates([], []).development_counts.rate is None


def test_candidate_id_is_canonical_and_unambiguous() -> None:
    a, b = Atom("A", "x&y", "a=b"), Atom("B", "z", "a:b")
    assert candidate_id((a, b)) == candidate_id((b, a))
    assert candidate_id((a, b)).startswith("hhhl-v4-variants.v1:")
    assert candidate_id((a,)) != candidate_id((Atom("A", "x", "y&a=b"),))
    with pytest.raises(ValueError, match="unique"):
        candidate_id((a, a))


def test_duplicate_event_ids_and_inconsistent_codes_are_rejected() -> None:
    a = Atom("A", "A", "high")
    row = block("one", (a,), known=1, hits=1)[0]
    for duplicate in (row, replace(row, cohort_id="P-over")):
        with pytest.raises(ValueError, match="duplicate event identity"):
            select_candidates((row, duplicate), (a,))
    with pytest.raises(ValueError, match="inconsistent code"):
        select_candidates((row, replace(row, code=codes()[1])), (a,))
    assert select_candidates((row, replace(row, horizon=252)), (a,)).development_counts.known == 1


def test_inventory_conflicts_bad_labels_and_multiple_feature_bins_are_rejected() -> None:
    a, other = Atom("A", "A", "high"), Atom("A", "A", "low")
    row = block("one", (a,), known=1, hits=1)[0]
    with pytest.raises(ValueError, match="invalid label"):
        replace(row, label="win")
    with pytest.raises(ValueError, match="duplicate inventory"):
        select_candidates([], (a, a))
    with pytest.raises(ValueError, match="inconsistent resolved families"):
        select_candidates([], (a, Atom("B", "A", "low")))
    with pytest.raises(ValueError, match="absent or inconsistent"):
        select_candidates((row,), ())
    with pytest.raises(ValueError, match="multiple bins"):
        select_candidates((replace(row, atoms=frozenset((a, other))),), (a, other))

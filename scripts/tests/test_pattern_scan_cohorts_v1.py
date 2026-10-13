from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import FrozenInstanceError
from typing import cast

import pytest

from research_core.pattern_scan_cohorts_v1 import PatternCohorts, build_pattern_cohorts


def _subtypes(result: PatternCohorts) -> dict[str, tuple[int, ...]]:
    return {cohort.subtype_id: cohort.retained_indices for cohort in result.subtype_cohorts}


@pytest.mark.parametrize(
    ("early", "confirmed", "confirmation_index"),
    [("R2a", "R2e", 101), ("R1a", "R1b", 108), ("R3a", "R3b", 110)],
)
def test_confirmation_subtypes_survive_union_cooldown(early: str, confirmed: str, confirmation_index: int) -> None:
    result = build_pattern_cohorts({early: [100], confirmed: [confirmation_index]})
    assert _subtypes(result) == {early: (100,), confirmed: (confirmation_index,)}
    assert result.union_indices == (100,)


def test_same_day_subtypes_each_survive_and_union_deduplicates() -> None:
    result = build_pattern_cohorts({"A": [100, 100], "B": [100]})
    assert _subtypes(result) == {"A": (100,), "B": (100,)}
    assert result.union_indices == (100,)


def test_each_subtype_has_independent_twenty_and_twenty_one_boundaries() -> None:
    result = build_pattern_cohorts({"A": [0, 20, 21], "B": [20, 40, 41]})
    assert _subtypes(result) == {"A": (0, 21), "B": (20, 41)}
    assert result.union_indices == (0, 21)


def test_union_uses_even_subtype_suppressed_raw_indices() -> None:
    result = build_pattern_cohorts({"A": [10, 30], "B": [0]})
    assert _subtypes(result) == {"A": (10,), "B": (0,)}
    # A's suppressed 30 survives union cooldown after B's 0 suppresses A's 10.
    assert result.union_indices == (0, 30)


def test_generators_stable_order_and_empty_subtypes() -> None:
    candidates: Mapping[str, Iterable[int]] = {"Z": (index for index in [30, 10]), "A": iter(()), " B ": [0]}
    result = build_pattern_cohorts(candidates)
    assert [cohort.subtype_id for cohort in result.subtype_cohorts] == [" B ", "A", "Z"]
    assert _subtypes(result) == {" B ": (0,), "A": (), "Z": (10,)}
    assert result.union_indices == (0, 30)


def test_lists_are_not_mutated_and_result_is_immutable() -> None:
    raw = [21, 0, 20, 21]
    candidates = {"A": raw}
    result = build_pattern_cohorts(candidates)
    assert candidates == {"A": [21, 0, 20, 21]}
    assert result.union_indices == (0, 21)
    with pytest.raises(FrozenInstanceError):
        setattr(result, "union_indices", ())
    with pytest.raises(FrozenInstanceError):
        setattr(result.subtype_cohorts[0], "retained_indices", ())


def test_empty_mapping_returns_empty_cohorts() -> None:
    assert build_pattern_cohorts({}) == PatternCohorts((), ())


@pytest.mark.parametrize("bad_id", ["", " ", "\t", 1, None])
def test_invalid_subtype_identifiers_fail(bad_id: object) -> None:
    candidates = cast("Mapping[str, Iterable[int]]", {bad_id: [0]})
    with pytest.raises(ValueError, match="subtype identifiers"):
        build_pattern_cohorts(candidates)


@pytest.mark.parametrize("bad_index", [-1, True, 1.5, "1", None])
def test_invalid_indices_use_existing_validator(bad_index: object) -> None:
    candidates = cast("Mapping[str, Iterable[int]]", {"A": [bad_index]})
    with pytest.raises(ValueError, match="session indices must be nonnegative integers"):
        build_pattern_cohorts(candidates)

"""Hand-calculable boundary tests for the supplied-value feature classifier."""

from __future__ import annotations

import math

import pytest

from research_core.hhhl_variants_features import FEATURES, classify_feature, selection_atoms


@pytest.mark.parametrize("feature_id", [key for key, definition in FEATURES.items() if definition.numeric_bins])
def test_every_numeric_boundary_is_disjoint_and_complete(feature_id: str) -> None:
    definition = FEATURES[feature_id]
    for item in definition.numeric_bins:
        for boundary in (item.lower, item.upper):
            if boundary is None:
                continue
            probes = (
                (boundary - 1, boundary, boundary + 1)
                if definition.discrete_count
                else (math.nextafter(boundary, -math.inf), boundary, math.nextafter(boundary, math.inf))
            )
            for probe in probes:
                if definition.discrete_count and probe < 0:
                    continue
                expected = [part.bin_id for part in definition.numeric_bins if part.contains(probe)]
                assert len(expected) == 1
                assert classify_feature(feature_id, probe).bin_id == expected[0]


@pytest.mark.parametrize(
    ("feature_id", "value", "expected"),
    [
        ("B", -0.01, "lt05"),
        ("C2", 0.0, "nonpositive"),
        ("D", 0.90, "090to100"),
        ("D", 1.0, "ge100"),
        ("F", 0.7, "le070"),
        ("F", 1.0, "070to100"),
        ("G", 1.5, "150to200"),
        ("H", 90.0, "ge90"),
        ("E3", 0, "zero"),
        ("E3", 1, "one"),
        ("E3", 4, "ge4"),
        ("J", 2, "one_to_two"),
        ("J", 3, "ge3"),
        ("C", 0, "none"),
        ("C", 2, "partial"),
        ("C", 4, "all"),
    ],
)
def test_meaningful_equalities(feature_id: str, value: float | int, expected: str) -> None:
    assert classify_feature(feature_id, value).bin_id == expected


@pytest.mark.parametrize("missing", [None, math.nan, math.inf, -math.inf])
def test_unknown_and_inapplicable_are_not_zero(missing: float | None) -> None:
    result = classify_feature("B", missing)
    assert result.status == "feature_unknown" and result.bin_id is None
    result = classify_feature("A", 0.0, applicable=False)
    assert result.status == "not_applicable" and result.bin_id is None
    assert classify_feature("I", "unknown").status == "feature_unknown"
    assert classify_feature("C3", 0.0, unknown_reason="warmup_insufficient").reason == "warmup_insufficient"


def test_categories_preserve_bool_and_validate_source_domain() -> None:
    assert classify_feature("E4_big", False).bin_id == "false"
    assert classify_feature("E4_cat", "range").bin_id == "range"
    with pytest.raises(ValueError, match="unexpected category"):
        classify_feature("E4_big", 0)
    with pytest.raises(ValueError, match="unexpected category"):
        classify_feature("I", "bull")
    with pytest.raises(ValueError, match="integer count"):
        classify_feature("E3", 1.5)


def test_diagnostics_and_alternative_bins_have_distinct_roles() -> None:
    atoms = selection_atoms()
    assert len({(atom.feature_id, atom.bin_id) for atom in atoms}) == len(atoms)
    assert all(not atom.selectable for atom in atoms if atom.family == "K")
    assert next(atom for atom in atoms if atom.feature_id == "E3" and atom.bin_id == "zero").selectable
    assert next(atom for atom in atoms if atom.feature_id == "G" and atom.bin_id == "lt150").selectable

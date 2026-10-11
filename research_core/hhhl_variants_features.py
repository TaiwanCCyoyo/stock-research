"""Versioned HHHL variants feature inventory and value-to-bin definitions.

This module classifies supplied values; it does not read or calculate market data.
The study's mission defines their price basis, windows and availability timing.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from numbers import Real
from typing import Any

from research_core.hhhl_variants_selection import Atom

DEFINITION_ID = "hhhl-variants-features.v1"


@dataclass(frozen=True)
class NumericBin:
    bin_id: str
    lower: float | None = None
    upper: float | None = None
    lower_inclusive: bool = True
    upper_inclusive: bool = False

    def contains(self, value: float) -> bool:
        above = self.lower is None or (value >= self.lower if self.lower_inclusive else value > self.lower)
        below = self.upper is None or (value <= self.upper if self.upper_inclusive else value < self.upper)
        return above and below


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    family: str
    pattern_only: bool = False
    overhead_only: bool = False
    diagnostic_only: bool = False
    numeric_bins: tuple[NumericBin, ...] = ()
    categories: tuple[tuple[str, str | int | bool], ...] = ()
    discrete_count: bool = False

    @property
    def bin_ids(self) -> tuple[str, ...]:
        return tuple(item.bin_id for item in self.numeric_bins) + tuple(item[0] for item in self.categories)


@dataclass(frozen=True)
class FeatureBin:
    feature_id: str
    bin_id: str | None
    status: str
    reason: str | None = None


def _intervals(names: tuple[str, ...], edges: tuple[float, ...]) -> tuple[NumericBin, ...]:
    limits: tuple[float | None, ...] = (None, *edges, None)
    return tuple(NumericBin(name, limits[i], limits[i + 1]) for i, name in enumerate(names))


_BOOLEAN = (("false", False), ("true", True))
_DEFINITIONS = (
    FeatureDefinition("A", "A", pattern_only=True, overhead_only=True, numeric_bins=_intervals(("lt10", "10to20", "20to40", "ge40"), (0.10, 0.20, 0.40))),
    FeatureDefinition("B", "B", pattern_only=True, numeric_bins=_intervals(("lt05", "05to10", "10to20", "ge20"), (0.05, 0.10, 0.20))),
    FeatureDefinition("B2", "B", pattern_only=True, numeric_bins=_intervals(("lt03", "03to08", "ge08"), (0.03, 0.08))),
    FeatureDefinition("C", "C", categories=(("none", 0), ("partial", 1), ("partial", 2), ("partial", 3), ("all", 4))),
    FeatureDefinition(
        "C2", "C", numeric_bins=(NumericBin("nonpositive", upper=0.0, upper_inclusive=True), NumericBin("positive", lower=0.0, lower_inclusive=False))
    ),
    FeatureDefinition("C3", "C", numeric_bins=_intervals(("lt10", "10to30", "30to60", "ge60"), (0.10, 0.30, 0.60))),
    FeatureDefinition("C4", "C", categories=_BOOLEAN),
    FeatureDefinition("D", "D", numeric_bins=_intervals(("lt090", "090to100", "ge100"), (0.90, 1.0))),
    FeatureDefinition("D2", "D", numeric_bins=_intervals(("lt150", "150to250", "ge250"), (1.5, 2.5))),
    FeatureDefinition("E", "E", pattern_only=True, discrete_count=True, numeric_bins=_intervals(("lt20", "20to60", "60to120", "ge120"), (20.0, 60.0, 120.0))),
    FeatureDefinition("E2", "E", pattern_only=True, numeric_bins=_intervals(("lt15", "15to30", "ge30"), (0.15, 0.30))),
    FeatureDefinition("E3", "E", pattern_only=True, discrete_count=True, numeric_bins=_intervals(("zero", "one", "two", "three", "ge4"), (1.0, 2.0, 3.0, 4.0))),
    FeatureDefinition("E4_cat", "E", pattern_only=True, categories=(("bottom", "bottom"), ("hhhl", "hhhl"), ("range", "range"))),
    FeatureDefinition("E4_big", "E", pattern_only=True, categories=_BOOLEAN),
    FeatureDefinition(
        "F",
        "F",
        numeric_bins=(
            NumericBin("le070", upper=0.7, upper_inclusive=True),
            NumericBin("070to100", lower=0.7, upper=1.0, lower_inclusive=False, upper_inclusive=True),
            NumericBin("gt100", lower=1.0, lower_inclusive=False),
        ),
    ),
    FeatureDefinition("G", "G", numeric_bins=_intervals(("lt150", "150to200", "200to300", "300to500", "ge500"), (1.5, 2.0, 3.0, 5.0))),
    FeatureDefinition("G2_limit", "G", categories=_BOOLEAN),
    FeatureDefinition("G2_position", "G", categories=_BOOLEAN),
    FeatureDefinition("H", "H", numeric_bins=_intervals(("lt70", "70to90", "ge90"), (70.0, 90.0))),
    FeatureDefinition("I", "I", categories=(("down", "down"), ("mixed", "mixed"), ("up", "up"))),
    FeatureDefinition("J", "J", discrete_count=True, numeric_bins=_intervals(("zero", "one_to_two", "ge3"), (1.0, 3.0))),
    FeatureDefinition("K", "K", diagnostic_only=True, numeric_bins=_intervals(("lt03", "03to05", "ge05"), (0.03, 0.05))),
    FeatureDefinition("K2", "K", diagnostic_only=True, numeric_bins=_intervals(("lt20", "20to50", "50to150", "ge150"), (20.0, 50.0, 150.0))),
    FeatureDefinition("K3", "K", diagnostic_only=True, categories=(("low", "low"), ("middle", "middle"), ("high", "high"))),
)
FEATURES = {definition.feature_id: definition for definition in _DEFINITIONS}


def feature_inventory() -> dict[str, Any]:
    """Return the sole machine-readable bin inventory, without duplicate C bins."""
    values = []
    for definition in _DEFINITIONS:
        item = asdict(definition)
        item["bin_ids"] = sorted(set(definition.bin_ids))
        values.append(item)
    return {"definition_id": DEFINITION_ID, "features": values}


def selection_atoms() -> tuple[Atom, ...]:
    """Known bins only; diagnostic K bins are marked unselectable."""
    return tuple(
        Atom(definition.family, definition.feature_id, bin_id, not definition.diagnostic_only)
        for definition in _DEFINITIONS
        for bin_id in sorted(set(definition.bin_ids))
    )


def classify_feature(feature_id: str, value: object, *, applicable: bool = True, unknown_reason: str | None = None) -> FeatureBin:
    """Never turn missing, unsupported or inapplicable values into the first bin."""
    definition = FEATURES[feature_id]
    if not applicable:
        return FeatureBin(feature_id, None, "not_applicable", "outside_feature_cohort")
    if unknown_reason is not None:
        if not unknown_reason.strip():
            raise ValueError("unknown_reason must be nonempty")
        return FeatureBin(feature_id, None, "feature_unknown", unknown_reason)
    if value is None or (isinstance(value, Real) and not isinstance(value, bool) and not math.isfinite(float(value))):
        return FeatureBin(feature_id, None, "feature_unknown", "missing_or_nonfinite")
    if feature_id == "I" and value == "unknown":
        return FeatureBin(feature_id, None, "feature_unknown", "source_market_unknown")
    if definition.categories:
        for bin_id, expected in definition.categories:
            if type(value) is type(expected) and value == expected:
                return FeatureBin(feature_id, bin_id, "known")
        raise ValueError(f"unexpected category for {feature_id}: {value!r}")
    if not isinstance(value, Real) or isinstance(value, bool):
        raise ValueError(f"numeric value required for {feature_id}")
    number = float(value)
    if definition.discrete_count and (number < 0 or not number.is_integer()):
        raise ValueError(f"nonnegative integer count required for {feature_id}")
    matches = [item.bin_id for item in definition.numeric_bins if item.contains(number)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one bin for {feature_id}")
    return FeatureBin(feature_id, matches[0], "known")

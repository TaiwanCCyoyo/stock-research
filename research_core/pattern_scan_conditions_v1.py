"""Approved condition inventory and vectorized bins for the multi-pattern study."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import numpy as np
import pandas as pd

from research_core.hhhl_variants_features import FEATURES as LEGACY_FEATURES
from research_core.hhhl_variants_features import FeatureDefinition, NumericBin
from research_core.hhhl_variants_selection import Atom

PATTERNS = ("H1", "B1", "B2", "B3", "B4", "R1", "R2", "R3", "P1", "L1", "L2", "L3")
DEFINITION_ID = "pattern-scan-conditions.v1"
BOOL = (("false", False), ("true", True))


def intervals(names: tuple[str, ...], edges: tuple[float, ...]) -> tuple[NumericBin, ...]:
    limits: tuple[float | None, ...] = (None, *edges, None)
    return tuple(NumericBin(name, limits[i], limits[i + 1]) for i, name in enumerate(names))


def inventory() -> dict[str, FeatureDefinition]:
    """Retain legacy numerical boundaries; change only the approved family map."""
    families = {
        "C": "MA",
        "C2": "MA",
        "C3": "MA",
        "C4": "MA",
        "D": "SR",
        "D2": "SR",
        "F": "VOLA",
        "G": "VOL",
        "G2_limit": "KL",
        "G2_position": "KL",
        "H": "RS",
        "J": "MKT",
        "K": "K",
        "K2": "K",
        "K3": "K",
        "A": "SR",
        "B": "SR",
        "B2": "SR",
        "E": "SR",
        "E2": "SR",
        "E3": "SR",
        "E4_cat": "SR",
        "E4_big": "SR",
    }
    result = {name: replace(LEGACY_FEATURES[name], family=family) for name, family in families.items()}
    new = (
        FeatureDefinition("MA_a", "MA", numeric_bins=intervals(("lt0", "0to05", "05to15", "ge15"), (0.0, 0.05, 0.15))),
        FeatureDefinition("MA_b", "MA", categories=BOOL),
        FeatureDefinition("BB_a", "BB", numeric_bins=intervals(("lt0", "0to05", "05to1", "ge1"), (0.0, 0.5, 1.0))),
        FeatureDefinition(
            "BB_b",
            "BB",
            numeric_bins=(
                NumericBin("le10", upper=10.0, upper_inclusive=True),
                NumericBin("10to50", 10.0, 50.0, False, True),
                NumericBin("gt50", 50.0, lower_inclusive=False),
            ),
        ),
        FeatureDefinition("BB_c", "BB", categories=BOOL),
        FeatureDefinition("SR_a", "SR", numeric_bins=intervals(("lt10", "10to20", "ge20"), (0.1, 0.2)), categories=(("none", "none"),)),
        FeatureDefinition("SR_b", "SR", numeric_bins=intervals(("lt05", "05to10", "10to20", "ge20"), (0.05, 0.1, 0.2))),
        FeatureDefinition("SR_c", "SR", categories=(("above", "above"), ("inside", "inside"), ("below", "below"))),
        FeatureDefinition("SR_support", "SR", pattern_only=True, numeric_bins=intervals(("lt05", "05to10", "10to20", "ge20"), (0.05, 0.1, 0.2))),
        FeatureDefinition("KL_a", "KL", numeric_bins=intervals(("lt03", "03to07", "ge07"), (0.3, 0.7))),
        FeatureDefinition("KL_b", "KL", numeric_bins=intervals(("lt01", "01to03", "ge03"), (0.1, 0.3))),
        FeatureDefinition("KL_c", "KL", categories=BOOL),
        FeatureDefinition("RSI", "IND", numeric_bins=intervals(("lt50", "50to70", "ge70"), (50.0, 70.0))),
        FeatureDefinition("MACD", "IND", categories=BOOL),
        FeatureDefinition("ADX", "IND", numeric_bins=intervals(("lt20", "20to25", "ge25"), (20.0, 25.0))),
        FeatureDefinition(
            "VOL_a",
            "VOL",
            numeric_bins=(
                NumericBin("le070", upper=0.7, upper_inclusive=True),
                NumericBin("070to100", 0.7, 1.0, False, True),
                NumericBin("gt100", 1.0, lower_inclusive=False),
            ),
        ),
        FeatureDefinition("MKT", "MKT", categories=tuple((state, state) for state in ("up", "down", "consolidation", "mixed"))),
    )
    result.update({item.feature_id: item for item in new})
    result.update({f"PAT_other_{pattern}": FeatureDefinition(f"PAT_other_{pattern}", "PAT", categories=BOOL) for pattern in PATTERNS})
    return result


FEATURES = inventory()


def selection_atoms() -> tuple[Atom, ...]:
    return tuple(Atom(item.family, item.feature_id, bin_id, not item.diagnostic_only) for item in FEATURES.values() for bin_id in dict.fromkeys(item.bin_ids))


def classify_column(
    feature_id: str,
    values: pd.Series,
    *,
    applicable: pd.Series | None = None,
    unknown_reason: pd.Series | None = None,
) -> pd.DataFrame:
    """No missing/unsupported value becomes zero or a selectable bin.

    Numeric/category mixed SR-a explicitly represents observed absence as none.
    The category 'unknown' in market context remains feature unknown.
    """
    definition = FEATURES[feature_id]
    allowed = pd.Series(True, index=values.index) if applicable is None else applicable
    reasons = pd.Series(None, index=values.index, dtype=object) if unknown_reason is None else unknown_reason
    if not allowed.index.equals(values.index) or not reasons.index.equals(values.index):
        raise ValueError("condition inputs must align")
    if allowed.isna().any() or not pd.api.types.is_bool_dtype(allowed):
        raise ValueError("applicable must be known boolean")
    result = pd.DataFrame({"bin_id": None, "status": "feature_unknown", "reason": "missing_or_nonfinite"}, index=values.index)
    result.loc[~allowed, ["status", "reason"]] = ["not_applicable", "outside_condition_cohort"]
    explicit = allowed & reasons.notna()
    if not reasons.loc[explicit].map(lambda value: isinstance(value, str) and bool(value.strip())).all():
        raise ValueError("explicit reason must be nonblank")
    result.loc[explicit, "reason"] = reasons.loc[explicit]
    active = allowed & ~explicit & values.notna()
    for bin_id, expected in definition.categories:
        if isinstance(expected, bool):
            typed = values.map(lambda value: isinstance(value, (bool, np.bool_)))
        elif isinstance(expected, int):
            typed = values.map(lambda value: isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_)))
        else:
            typed = values.map(lambda value: isinstance(value, type(expected)))
        matched = active & typed & values.eq(expected).fillna(False)
        result.loc[matched, ["bin_id", "status", "reason"]] = [bin_id, "known", None]
    if definition.numeric_bins:
        numbers = cast(pd.Series, pd.to_numeric(values, errors="coerce"))
        valid_type = values.map(lambda value: isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(value, (bool, np.bool_)))
        numeric = active & valid_type & pd.Series(np.isfinite(numbers.to_numpy(dtype=float, na_value=np.nan)), index=values.index)
        if definition.discrete_count and ((numbers.loc[numeric] < 0) | (numbers.loc[numeric] != np.floor(numbers.loc[numeric]))).any():
            raise ValueError("count condition requires nonnegative integers")
        for interval in definition.numeric_bins:
            matched = numeric.copy()
            if interval.lower is not None:
                matched &= numbers.ge(interval.lower) if interval.lower_inclusive else numbers.gt(interval.lower)
            if interval.upper is not None:
                matched &= numbers.le(interval.upper) if interval.upper_inclusive else numbers.lt(interval.upper)
            result.loc[matched, ["bin_id", "status", "reason"]] = [interval.bin_id, "known", None]
    nonfinite = values.map(lambda value: isinstance(value, (int, float, np.integer, np.floating)) and not np.isfinite(value))
    unsupported = active & ~nonfinite & result["status"].ne("known")
    if feature_id == "MKT":
        unsupported &= values.ne("unknown")
    if unsupported.any():
        raise ValueError(f"unsupported {feature_id} values: {values.loc[unsupported].head(3).tolist()}")
    return result


def inventory_json() -> dict[str, Any]:
    from dataclasses import asdict

    return {"definition_id": DEFINITION_ID, "features": [asdict(item) for item in FEATURES.values()], "pattern_ids": list(PATTERNS)}

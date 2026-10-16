"""Per-stock scalar memoization over the unchanged public condition classifier."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from research_core.pattern_scan_conditions_v1 import FEATURES, classify_column

ScalarKey = tuple[Any, ...]
ClassificationKey = tuple[str, ScalarKey, bool, ScalarKey]
Classification = tuple[Any, Any, Any]
COLUMNS = ("bin_id", "status", "reason")


def _scalar_key(value: Any) -> ScalarKey | None:
    """Retain actual scalar types and exact float bits; share missing semantics."""
    if value is None or value is pd.NA:
        return ("missing",)
    scalar_type = type(value)
    if scalar_type is float or scalar_type in (np.float16, np.float32, np.float64):
        number = float(value)
        return ("missing",) if math.isnan(number) else (scalar_type, number.hex())
    if scalar_type in (bool, np.bool_, int, str):
        return (scalar_type, value)
    if isinstance(value, np.integer):
        return (scalar_type, int(value))
    return None


class ConditionClassificationCache:
    """Cache successful immutable result tuples, never caller frames or indices.

    Each instance belongs to one stock's event binding. Only first-use keys in
    the supplied Series are classified, together in one public classifier call.
    Native/extension value dtypes and unsupported inputs use the original call,
    preserving dtype-dependent numerical comparisons as well as error ordering
    and first-three unsupported examples, without committing partial entries.
    """

    def __init__(self) -> None:
        self._entries: dict[ClassificationKey, Classification] = {}

    def classify(self, feature_id: str, values: pd.Series, *, applicable: pd.Series, unknown_reason: pd.Series) -> pd.DataFrame:
        def fallback() -> pd.DataFrame:
            return classify_column(feature_id, values, applicable=applicable, unknown_reason=unknown_reason)

        if (
            feature_id not in FEATURES
            or values.dtype != object
            or not applicable.index.equals(values.index)
            or not unknown_reason.index.equals(values.index)
            or not pd.api.types.is_bool_dtype(applicable)
            or applicable.isna().any()
        ):
            return fallback()
        keys: list[ClassificationKey] = []
        first_use: dict[ClassificationKey, tuple[Any, bool, Any]] = {}
        for value, allowed, reason in zip(values, applicable, unknown_reason):
            value_key, reason_key = _scalar_key(value), _scalar_key(reason)
            if value_key is None or reason_key is None or (reason_key != ("missing",) and (type(reason) is not str or not reason.strip())):
                return fallback()
            key = (feature_id, value_key, bool(allowed), reason_key)
            keys.append(key)
            if key not in self._entries and key not in first_use:
                first_use[key] = (value, bool(allowed), reason)
        if first_use:
            unique = list(first_use.values())
            try:
                classified = classify_column(
                    feature_id,
                    pd.Series([row[0] for row in unique], dtype=object),
                    applicable=pd.Series([row[1] for row in unique], dtype=bool),
                    unknown_reason=pd.Series([row[2] for row in unique], dtype=object),
                )
            except (ValueError, TypeError, OverflowError):
                # Re-run with the exact original Series for complete error text.
                # No successful prefix from an invalid batch enters the cache.
                return fallback()
            pending: dict[ClassificationKey, Classification] = {
                key: (row[0], row[1], row[2]) for key, row in zip(first_use, classified.itertuples(index=False, name=None))
            }
            self._entries.update(pending)
        return pd.DataFrame([self._entries[key] for key in keys], index=values.index.copy(deep=True), columns=pd.Index(COLUMNS), dtype=object)

"""One explicit identity adapter for selected gap-reset stock features."""

from __future__ import annotations

from typing import Any

from research_core.derived_features_selective_v1 import ALL_FEATURES, definition_metadata
from research_core.feature_identity_v1 import validate_identity


def make_feature_identity(
    feature: str, code: str, input_digest: str, calendar: dict[str, Any], implementation: dict[str, str], runtime: dict[str, str], price_basis: str
) -> dict[str, Any]:
    if feature not in ALL_FEATURES:
        raise ValueError("unsupported selected stock feature")
    metadata = definition_metadata()
    return validate_identity({
        "schema": "research-feature-block.v1",
        "feature_id": feature,
        "definition": {"id": metadata["version"], "version": metadata["numerical_definition_version"], "metadata": metadata},
        "stock_code": code,
        "scope": "stock",
        "inputs": {"prepared": input_digest},
        "implementation": implementation,
        "calendar": calendar,
        "semantics": {
            "price_basis": price_basis,
            "gap": metadata["gap_policy"],
            "warmup": "Feature-specific consecutive-row seeds in definition metadata",
            "pivot_availability": metadata["pivots"]["availability"],
            "calendar_policy": "Explicit supplied daily DatetimeIndex; no dropping or filling",
            "quality_policy": metadata["validity"],
        },
        "parameters": {},
        "runtime": runtime,
        "context": None,
    })

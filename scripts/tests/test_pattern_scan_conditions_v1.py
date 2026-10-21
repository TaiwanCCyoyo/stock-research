import numpy as np
import pandas as pd
import pytest

from research_core.hhhl_variants_daily import bin_values
from research_core.pattern_scan_conditions_v1 import FEATURES, classify_column, selection_atoms


@pytest.mark.parametrize(
    "feature,values",
    [("C", [0.0, 1.0, 3.0, 4.0, np.nan]), ("F", [0.7, 1.0, 1.01, np.nan]), ("G", [1.49, 1.5, 2.0, 5.0, np.nan]), ("K2", [19.0, 20.0, 50.0, 150.0, np.nan])],
)
def test_retained_bins_equal_public_source(feature: str, values: list[float]) -> None:
    series = pd.Series(values)
    old = bin_values(feature, series)
    new = classify_column(feature, series)
    assert new["bin_id"].fillna("").tolist() == old[f"{feature}_bin"].fillna("").tolist()
    assert new["status"].tolist() == old[f"{feature}_status"].tolist()


def test_inclusive_ecdf_boundaries_and_raw_macd_boolean_types() -> None:
    assert classify_column("BB_b", pd.Series([10.0, 10.01, 50.0, 50.01]))["bin_id"].tolist() == ["le10", "10to50", "10to50", "gt50"]
    assert classify_column("MACD", pd.Series([True, False, None]))["status"].tolist() == ["known", "known", "feature_unknown"]
    with pytest.raises(ValueError, match="unsupported"):
        classify_column("MACD", pd.Series([1]))


def test_missing_absent_unknown_and_inapplicable_are_distinct() -> None:
    result = classify_column("SR_a", pd.Series(["none", 0.1, np.nan], dtype=object))
    assert result["bin_id"].tolist() == ["none", "10to20", None]
    market = classify_column("MKT", pd.Series(["consolidation", "unknown"]))
    assert market["status"].tolist() == ["known", "feature_unknown"]
    support = classify_column("SR_support", pd.Series([0.0]), applicable=pd.Series([False]))
    assert support["status"].item() == "not_applicable"


def test_resolved_families_exclude_k_and_remap_h1_features() -> None:
    atoms = selection_atoms()
    assert len({(atom.feature_id, atom.bin_id) for atom in atoms}) == len(atoms)
    assert len(atoms) <= 320
    assert all(not atom.selectable for atom in atoms if atom.family == "K")
    assert all(FEATURES[key].family == "SR" for key in ("A", "B", "B2", "E", "E2", "E3", "E4_cat", "E4_big"))


def test_nonfinite_numbers_are_unknown_and_numeric_booleans_rejected() -> None:
    assert classify_column("MA_a", pd.Series([np.inf, -np.inf, np.nan]))["status"].tolist() == ["feature_unknown"] * 3
    with pytest.raises(ValueError, match="unsupported"):
        classify_column("MA_a", pd.Series([True]))

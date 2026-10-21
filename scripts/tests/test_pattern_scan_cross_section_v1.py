"""Invented full-pool barriers and three-state PAT causal windows."""

from typing import cast

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from research_core.hhhl_variants_run import cross_section as legacy_cross_section
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_cross_section_v1 import cross_section, recent_pattern_values

POOL = ("TW:001", "TW:002", "TW:003")


def pool(length: int = 14) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for code in POOL:
        for index, date in enumerate(pd.bdate_range("2020-01-06", periods=length)):
            rows.append({
                "security_id": code,
                "calendar_index": index,
                "t0": date.strftime("%Y-%m-%d"),
                "base_eligible": True,
                "ret120": 0.5,
                "turnover20": 100.0,
                "industry_ref": "i" if code != POOL[2] else None,
                "is_cnh": code == POOL[0] and index in (0, 1, 10),
            })
    return pd.DataFrame(rows)


def test_parity_ties_distinct_other_stock_and_input_preservation() -> None:
    source = pool().sample(frac=1, random_state=10)
    original = source.copy(deep=True)
    actual = cross_section(source, expected_security_ids=POOL)
    adapted = source.reset_index(drop=True).copy()
    adapted["code"] = adapted.security_id
    adapted["Date"] = pd.to_datetime(adapted.t0)
    adapted["legacy_liquid"] = adapted.base_eligible
    expected, _ = legacy_cross_section(adapted)
    for column in ("H", "K3", "J", "H_applicable", "K3_applicable", "H_unknown_reason", "K3_unknown_reason", "J_unknown_reason"):
        pd.testing.assert_series_equal(actual[column].reset_index(drop=True), expected[column])
    assert np.allclose(actual.H, 200 / 3)
    assert actual.K3.eq("low").all()
    assert actual.loc[actual.security_id.eq(POOL[1]) & actual.calendar_index.eq(10), "J"].iloc[0] == 1
    assert actual.loc[actual.security_id.eq(POOL[0]) & actual.calendar_index.eq(10), "J"].iloc[0] == 0
    assert actual.loc[actual.security_id.eq(POOL[2]), "J_unknown_reason"].eq("industry_unclassified").all()
    pd.testing.assert_frame_equal(source, original)


def test_eligibility_missingness_and_thirds() -> None:
    source = pool()
    source.loc[source.security_id.eq(POOL[0]), "turnover20"] = 10.0
    source.loc[source.security_id.eq(POOL[2]), "turnover20"] = 300.0
    source.loc[source.security_id.eq(POOL[1]) & source.calendar_index.eq(12), ["ret120", "turnover20"]] = np.nan
    source.loc[source.security_id.eq(POOL[2]) & source.calendar_index.eq(13), "base_eligible"] = False
    result = cross_section(source, expected_security_ids=POOL)
    assert result.loc[result.calendar_index.eq(11), "K3"].tolist() == ["low", "middle", "high"]
    missing = result.loc[result.security_id.eq(POOL[1]) & result.calendar_index.eq(12)].iloc[0]
    assert pd.isna(missing.H) and pd.isna(missing.K3)
    assert missing.H_unknown_reason == "warmup_insufficient"
    assert missing.K3_unknown_reason == "warmup_insufficient_after_gap"
    excluded = result.loc[result.security_id.eq(POOL[2]) & result.calendar_index.eq(13)].iloc[0]
    assert not excluded.H_applicable and not excluded.K3_applicable


@pytest.mark.parametrize("invalid", ["pool", "duplicate", "missing_row", "date_conflict", "date_alias", "date_duplicate", "index_gap", "suffix", "boolean"])
def test_reject_incomplete_or_ambiguous_barriers(invalid: str) -> None:
    source = pool()
    if invalid == "pool":
        source = source.loc[source.security_id.ne(POOL[2])]
    elif invalid == "duplicate":
        source = pd.concat([source, source.iloc[:1]])
    elif invalid == "missing_row":
        source = source.iloc[1:]
    elif invalid == "date_conflict":
        source.loc[0, "t0"] = "2020-01-01"
    elif invalid == "date_alias":
        source.loc[0, "t0"] = "2020-1-6"
    elif invalid == "date_duplicate":
        source.loc[source.calendar_index.eq(1), "t0"] = "2020-01-06"
    elif invalid == "index_gap":
        source.loc[source.calendar_index.ge(5), "calendar_index"] += 1
    elif invalid == "suffix":
        source = source.loc[source.calendar_index.ge(3)]
    else:
        source["base_eligible"] = 1
    with pytest.raises(ValueError):
        cross_section(source, expected_security_ids=POOL)


@pytest.mark.parametrize("expected", [(), (POOL[0], POOL[0]), ("",), "TW:001"])
def test_expected_pool_is_required_and_explicit(expected: tuple[str, ...] | str) -> None:
    with pytest.raises(ValueError):
        cross_section(pool(), expected_security_ids=expected)


def test_barrier_prefix_has_no_future_dependence() -> None:
    source = pool(25)
    full = cross_section(source, expected_security_ids=POOL)
    early_source = source.loc[source.calendar_index.lt(14)]
    early = cross_section(early_source, expected_security_ids=POOL)
    pd.testing.assert_frame_equal(early, full.loc[early.index])


def states(length: int = 25) -> dict[str, NDArray[np.int8]]:
    return {pattern: np.zeros((2, length), dtype=np.int8) for pattern in PATTERNS}


def test_pat_raw_union_recent_window_warmup_unknown_and_true_absorption() -> None:
    source = states()
    source["B1"][0, 0] = 1
    source["B1"][0, 5] = -1
    source["L3"][1, 10] = 1
    original = {pattern: values.copy() for pattern, values in source.items()}
    result = recent_pattern_values(source, "H1")
    assert "PAT_other_H1" not in result and len(result) == 11
    b1 = result["PAT_other_B1"]
    assert np.all(b1[0, :11] == 1)
    assert np.all(b1[0, 11:16] == -1)
    assert b1[0, 16] == 0
    assert np.all(b1[1, :10] == -1) and b1[1, 10] == 0
    assert np.all(result["PAT_other_L3"][1, 10:21] == 1)
    assert result["PAT_other_L3"][1, 21] == 0
    for pattern in PATTERNS:
        np.testing.assert_array_equal(source[pattern], original[pattern])


@pytest.mark.parametrize("end", [0, 1, 10, 11, 20])
def test_pat_prefix_invariance(end: int) -> None:
    source = states()
    source["R2"][0, 4] = 1
    source["B3"][1, 8] = -1
    full = recent_pattern_values(source, "H1")
    prefix = recent_pattern_values({pattern: values[:, :end] for pattern, values in source.items()}, "H1")
    for feature in full:
        np.testing.assert_array_equal(prefix[feature], full[feature][:, :end])


@pytest.mark.parametrize("invalid", ["family", "shape", "dtype", "value", "own"])
def test_pat_invalid_input_fails(invalid: str) -> None:
    source = states()
    own = "H1"
    if invalid == "family":
        del source["B1"]
    elif invalid == "shape":
        source["B1"] = np.zeros((3, 25), dtype=np.int8)
    elif invalid == "dtype":
        source["B1"] = cast(NDArray[np.int8], np.zeros((2, 25), dtype=float))
    elif invalid == "value":
        source["B1"][0, 0] = 2
    else:
        own = "other"
    with pytest.raises(ValueError):
        recent_pattern_values(source, own)

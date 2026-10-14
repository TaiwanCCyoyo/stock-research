"""Synthetic event identity, condition applicability and source-isolation cases."""

import json
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_classification_cache_v1 import ConditionClassificationCache
from research_core.pattern_scan_conditions_v1 import FEATURES, PATTERNS
from research_core.pattern_scan_event_conditions_v1 import atoms_for_pattern, event_conditions


def test_one_stock_classification_cache_preserves_all_targets_and_inputs() -> None:
    events, indicators, common = inputs()
    common["SR_a"] = pd.Series(["none"] * len(common), index=common.index, dtype=object)
    originals = [frame.copy(deep=True) for frame in (events, indicators, common)]
    cache = ConditionClassificationCache()
    for target in PATTERNS:
        expected = event_conditions(events, indicators, common, target_pattern=target)
        actual = event_conditions(events, indicators, common, target_pattern=target, classification_cache=cache)
        pd.testing.assert_frame_equal(actual, expected)
    for frame, original in zip((events, indicators, common), originals):
        pd.testing.assert_frame_equal(frame, original)


def inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    dates = pd.bdate_range("2020-01-06", periods=50)
    indicators = pd.DataFrame({"Close": 100.0, "Low": 80.0}, index=dates)
    common = pd.DataFrame(
        {"security_id": "TW:001", "G": 1.2, "H": 75.0, "H_applicable": True, "J": 1.0, "K3": "middle", "MKT": "mixed", "MA_b": False}, index=dates
    )
    for pattern in PATTERNS:
        common[f"PAT_other_{pattern}"] = np.int8(0)
    source = {
        "restart": 10,
        "seq": [{"k": "H", "rel": "higher", "p": 110.0, "i": 20}, {"k": "L", "rel": "higher", "p": 90.0, "i": 25}],
        "bonus_levels": [{"age": "old", "level": 120.0}],
        "cat": "hhhl",
        "big_hhhl": False,
        "vx": 3.4,
    }
    events: list[dict[str, Any]] = []
    for pattern, support in (("B1", 90.0), ("L1", 80.0), ("C-base", None), ("H1", 90.0)):
        events.append({
            "event_id": f"synthetic:{pattern}",
            "security_id": "TW:001",
            "t0": dates[30].strftime("%Y-%m-%d"),
            "calendar_index": 30,
            "pattern_id": pattern,
            "support": support,
            "pivot": 95.0,
            "details_json": json.dumps({"source_event_json": json.dumps(source)}),
        })
    return pd.DataFrame(events), indicators, common


def test_same_day_support_distinct_controls_and_h1_source_override() -> None:
    events, indicators, common = inputs()
    originals = [source.copy(deep=True) for source in (events, indicators, common)]
    result = event_conditions(events, indicators, common, target_pattern="B1")
    assert result.SR_support.iloc[0] == pytest.approx(100 / 90 - 1)
    assert result.SR_support.iloc[1] == pytest.approx(0.25)
    assert result.SR_support_status.iloc[2] == "not_applicable" and result.SR_support.iloc[2] is None
    assert result.A_status.iloc[:3].eq("not_applicable").all()
    assert result.A.iloc[3] == pytest.approx(0.2)
    assert result.G.iloc[:3].tolist() == [1.2, 1.2, 1.2]
    assert result.G.iloc[3] == 3.4 and result.G_bin.iloc[3] == "300to500"
    assert result.B.iloc[3] == pytest.approx(100 / 90 - 1)
    assert result.E.iloc[3] == 20 and result.E3.iloc[3] == 2
    assert result.MA_b_bin.eq("false").all()
    assert len(result.columns) == 1 + 4 * len(FEATURES)
    for source, original in zip((events, indicators, common), originals):
        pd.testing.assert_frame_equal(source, original)


def test_missing_support_unknown_and_clean_h1_overhead_not_applicable() -> None:
    events, indicators, common = inputs()
    events.loc[0, "support"] = None
    details = json.loads(events.details_json.iloc[3])
    source = json.loads(details["source_event_json"])
    source["bonus_levels"] = []
    events.loc[3, "details_json"] = json.dumps({"source_event_json": json.dumps(source)})
    result = event_conditions(events, indicators, common, target_pattern="H1")
    assert result.SR_support_status.iloc[0] == "feature_unknown"
    assert result.SR_support_reason.iloc[0] == "missing_event_support"
    assert result.A_status.iloc[3] == "not_applicable"
    assert result.A.iloc[3] is None


def test_pat_self_unknown_false_and_strict_integer_states() -> None:
    events, indicators, common = inputs()
    common.loc[common.index[30], "PAT_other_L1"] = np.int8(-1)
    result = event_conditions(events, indicators, common, target_pattern="B1")
    assert result.PAT_other_B1_status.eq("not_applicable").all()
    assert result.PAT_other_B1.isna().all()
    assert result.PAT_other_L1_status.eq("feature_unknown").all()
    assert result.PAT_other_L1_reason.eq("pattern_window_unknown").all()
    assert result.PAT_other_R2_bin.eq("false").all()
    common["PAT_other_R2"] = 0.0
    with pytest.raises(ValueError, match="integer"):
        event_conditions(events, indicators, common, target_pattern="B1")


def test_missing_columns_unknown_context_normalized_and_caller_applicability() -> None:
    events, indicators, common = inputs()
    common["MKT"] = "unknown"
    common["H_applicable"] = False
    common["G_unknown_reason"] = "generic_volume_missing"
    result = event_conditions(events, indicators, common, target_pattern="B1")
    assert result.BB_a_status.eq("feature_unknown").all()
    assert result.BB_a_reason.eq("missing_source_column").all()
    assert result.MKT_reason.eq("market_context_unknown").all()
    assert result.H_status.eq("not_applicable").all() and result.H.isna().all()
    assert result.G_reason.iloc[:3].eq("generic_volume_missing").all()
    assert result.G_status.iloc[3] == "known"  # H1 uses its own G provenance.


def test_pattern_atoms_exclude_self_pat_and_unrelated_h1_fields() -> None:
    b1 = atoms_for_pattern("B1")
    h1 = atoms_for_pattern("H1")
    assert not any(atom.feature_id == "PAT_other_B1" for atom in b1)
    assert not any(atom.feature_id in {"A", "B", "B2", "E", "E2", "E3", "E4_cat", "E4_big"} for atom in b1)
    assert any(atom.feature_id == "SR_support" for atom in b1)
    assert any(atom.feature_id == "A" for atom in h1)
    with pytest.raises(ValueError):
        atoms_for_pattern("C-base")


def test_only_t0_and_preserved_causal_h1_metadata_are_read() -> None:
    events, indicators, common = inputs()
    baseline = event_conditions(events, indicators, common, target_pattern="H1")
    changed = common.copy()
    changed.loc[changed.index[31:], "G"] = 999.0
    changed_indicators = indicators.copy()
    changed_indicators.loc[changed_indicators.index[31:], ["Close", "Low"]] = 500.0
    pd.testing.assert_frame_equal(event_conditions(events, changed_indicators, changed, target_pattern="H1"), baseline)
    pd.testing.assert_frame_equal(event_conditions(events, indicators.iloc[:31], common.iloc[:31], target_pattern="H1"), baseline)


@pytest.mark.parametrize("invalid", ["alignment", "t0", "position", "duplicate", "stock", "applicable", "timezone"])
def test_calendar_identity_and_source_validation(invalid: str) -> None:
    events, indicators, common = inputs()
    if invalid == "alignment":
        common = common.iloc[1:]
    elif invalid == "t0":
        events.loc[0, "t0"] = "2020-1-1"
    elif invalid == "position":
        events.loc[0, "calendar_index"] = 100
    elif invalid == "duplicate":
        events.loc[0, "event_id"] = events.event_id.iloc[1]
    elif invalid == "stock":
        common["security_id"] = "TW:other"
    elif invalid == "applicable":
        common["H_applicable"] = 1
    else:
        indicators.index = cast(pd.DatetimeIndex, indicators.index).tz_localize("Asia/Taipei")
        common.index = indicators.index
    with pytest.raises(ValueError):
        event_conditions(events, indicators, common, target_pattern="B1")


def test_empty_events_still_has_the_full_wide_schema() -> None:
    events, indicators, common = inputs()
    result = event_conditions(events.iloc[:0], indicators, common, target_pattern="B1")
    assert result.empty and len(result.columns) == 1 + 4 * len(FEATURES)


@pytest.mark.parametrize("invalid", (0.0, 1.0, -1.0, True, np.bool_(False), 2, "1"))
def test_pat_noninteger_boolean_and_out_of_range_states_rejected(invalid: Any) -> None:
    events, indicators, common = inputs()
    common["PAT_other_R2"] = common.PAT_other_R2.astype(object)
    common.loc[common.index[30], "PAT_other_R2"] = invalid
    before = common.copy(deep=True)
    with pytest.raises(ValueError, match="PAT source states must be integer -1/0/1"):
        event_conditions(events, indicators, common, target_pattern="B1")
    pd.testing.assert_frame_equal(common, before)


@pytest.mark.parametrize("missing", (None, np.nan, pd.NA))
def test_pat_mixed_known_unknown_missing_and_self_applicability(missing: Any) -> None:
    events, indicators, common = inputs()
    for index, position in enumerate((30, 31, 32, 33)):
        events.loc[index, "calendar_index"] = position
        events.loc[index, "t0"] = pd.DatetimeIndex(common.index)[position].strftime("%Y-%m-%d")
    common["PAT_other_R2"] = common.PAT_other_R2.astype(object)
    common.loc[common.index[30:34], "PAT_other_R2"] = [np.int8(-1), missing, np.int64(0), 1]
    common["PAT_other_B1"] = True  # Self PAT remains N/A without validating unused states.
    originals = [frame.copy(deep=True) for frame in (events, indicators, common)]
    result = event_conditions(events, indicators, common, target_pattern="B1")
    assert result.PAT_other_R2.tolist() == [None, None, False, True]
    assert result.PAT_other_R2_status.tolist() == ["feature_unknown", "feature_unknown", "known", "known"]
    assert result.PAT_other_R2_bin.tolist()[2:] == ["false", "true"]
    assert result.PAT_other_R2_reason.tolist() == ["pattern_window_unknown", "pattern_window_unknown", None, None]
    assert result.PAT_other_B1_status.eq("not_applicable").all()
    assert result.PAT_other_B1.isna().all()
    for frame, original in zip((events, indicators, common), originals):
        pd.testing.assert_frame_equal(frame, original)
    with_reason = common.copy(deep=True)
    with_reason["PAT_other_R2_unknown_reason"] = "retained_source_reason"
    reason_result = event_conditions(events, indicators, with_reason, target_pattern="B1")
    assert reason_result.PAT_other_R2_reason.tolist() == [
        "pattern_window_unknown",
        "pattern_window_unknown",
        "retained_source_reason",
        "retained_source_reason",
    ]
    assert reason_result.PAT_other_R2_status.eq("feature_unknown").all()

"""Hand-calculated event lookbacks over unchanged synthetic base labels."""

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from research_core.pattern_scan_event_outcomes_v1 import EventIdentity
from research_core.pattern_scan_projection_v1 import project_outcomes


def inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    dates = pd.bdate_range("2020-01-06", periods=160)
    events: list[dict[str, Any]] = []
    for pattern, start in (("B1", 0), ("L1", 60)):
        identity = EventIdentity("TW:001", str(dates[70].strftime("%Y-%m-%d")), pattern, "original", "definition-v1", "input-v1")
        events.append({
            "security_id": identity.security_id,
            "event_id": identity.event_id,
            "t0": identity.t0,
            "pattern_id": pattern,
            "subtype_id": "original",
            "definition_id": "definition-v1",
            "input_id": "input-v1",
            "calendar_index": 70,
            "window_start": start,
            "base_eligible": True,
            "eligibility_reason": None,
            "details_json": '{"kept":true}',
            "cohort_id": "original",
        })
    labels = pd.DataFrame([
        {
            "security_id": "TW:001",
            "t0": dates[70].strftime("%Y-%m-%d"),
            "calendar_index": 70,
            "horizon": horizon,
            "label": "hit",
            "calendar_full": full,
            "main_eligible": full,
            "unknown_reason": None,
        }
        for horizon, full in ((20, True), (126, False))
    ])
    return pd.DataFrame(events), labels, pd.Series(None, index=dates, dtype=object)


def project(events: pd.DataFrame, labels: pd.DataFrame, reasons: pd.Series) -> pd.DataFrame:
    return project_outcomes(events, labels, reasons, base_label_version_id="synthetic-labels-v1", base_label_manifest_sha256="a" * 64)


def test_same_base_independent_detection_windows_and_original_bytes() -> None:
    events, labels, reasons = inputs()
    events_original, labels_original = events.copy(deep=True), labels.copy(deep=True)
    reasons.iloc[20] = "missing_official_quote|unexplained_adjusted_jump"
    result = project(events, labels, reasons)
    short = result.loc[result.horizon.eq(20)]
    assert short.effective_label.tolist() == ["unknown", "hit"]
    assert short.event_main_eligible.tolist() == [False, True]
    assert result.base_label.eq("hit").all()
    assert result.details_json.eq('{"kept":true}').all()
    assert json.loads(result.detection_quality_reasons_json.iloc[0]) == ["unexplained_jump"]
    assert json.loads(result.effective_unknown_reasons_json.iloc[0]) == ["detection:unexplained_jump"]
    assert json.loads(result.detection_scope_json.iloc[2]) == {"start": 60, "end": 70}
    assert result.base_label_manifest_sha256.eq("a" * 64).all()
    pd.testing.assert_frame_equal(events, events_original)
    pd.testing.assert_frame_equal(labels, labels_original)


def test_result_scopes_differ_by_horizon_and_override_early_hit() -> None:
    events, labels, reasons = inputs()
    reasons.iloc[100] = "unexplained_jump"
    result = project(events, labels, reasons)
    assert result.loc[result.horizon.eq(20), "effective_label"].eq("hit").all()
    assert result.loc[result.horizon.eq(126), "effective_label"].eq("unknown").all()
    assert json.loads(result.result_scope_json.iloc[0]) == {"start": 71, "end": 90}
    assert json.loads(result.result_scope_json.iloc[1]) == {"start": 71, "end": 159}
    assert json.loads(result.result_quality_reasons_json.iloc[1]) == ["unexplained_jump"]
    reasons.iloc[90] = "unexplained_jump"
    assert project(events, labels, reasons).effective_label.eq("unknown").all()


def test_ordinary_missing_after_hit_censored_and_eligibility_only_exclusions() -> None:
    events, labels, reasons = inputs()
    reasons.iloc[80] = "missing_official_quote|invalid_ohlc"
    events.loc[0, "base_eligible"] = False
    events.loc[0, "eligibility_reason"] = "not_liquid|insufficient_history|not_liquid"
    result = project(events, labels, reasons)
    assert result.effective_label.eq("hit").all()
    assert result.loc[result.pattern_id.eq("B1"), "event_eligibility_excluded"].all()
    assert not result.loc[result.pattern_id.eq("B1"), "event_main_eligible"].any()
    assert not result.loc[result.horizon.eq(126), "event_main_eligible"].any()
    assert json.loads(result.event_eligibility_reasons_json.iloc[0]) == ["insufficient_history", "not_liquid"]
    assert result.effective_unknown_reasons_json.eq("[]").all()


def test_base_unknown_reason_retained_with_result_jump() -> None:
    events, labels, reasons = inputs()
    labels.loc[0, ["label", "main_eligible", "unknown_reason"]] = ["unknown", False, "missing_before_decision"]
    reasons.iloc[80] = "unexplained_jump"
    result = project(events, labels, reasons)
    assert result.base_label.iloc[0] == "unknown"
    assert json.loads(result.effective_unknown_reasons_json.iloc[0]) == ["base:missing_before_decision", "result:unexplained_jump"]


@pytest.mark.parametrize(
    "invalid",
    [
        "event_id",
        "duplicate_event",
        "duplicate_label",
        "t0",
        "window",
        "no_label",
        "stock",
        "eligibility",
        "label_state",
        "position",
        "bool_position",
        "horizon",
        "quality_calendar",
    ],
)
def test_reject_noncanonical_inputs(invalid: str) -> None:
    events, labels, reasons = inputs()
    if invalid == "event_id":
        events.loc[0, "event_id"] = "not-identity"
    elif invalid == "duplicate_event":
        events = pd.concat([events, events.iloc[:1]])
    elif invalid == "duplicate_label":
        labels = pd.concat([labels, labels.iloc[:1]])
    elif invalid == "t0":
        labels.loc[0, "t0"] = "2020-1-1"
    elif invalid == "window":
        events.loc[0, "window_start"] = 71
    elif invalid == "no_label":
        labels = labels.iloc[:0]
    elif invalid == "stock":
        labels.loc[0, "security_id"] = "TW:002"
    elif invalid == "eligibility":
        events.loc[0, "base_eligible"] = False
    elif invalid == "label_state":
        labels.loc[0, "main_eligible"] = False
    elif invalid in {"position", "bool_position"}:
        events["calendar_index"] = events.calendar_index.astype(object)
        events.loc[0, "calendar_index"] = 0.5 if invalid == "position" else True
    elif invalid == "horizon":
        labels.loc[0, "horizon"] = 0
    else:
        reasons.index = pd.DatetimeIndex([reasons.index[0]] * len(reasons))
    with pytest.raises(ValueError):
        project(events, labels, reasons)


@pytest.mark.parametrize("version,manifest", [("", "a" * 64), ("v1", "a" * 63), ("v1", "z" * 64), ("v1", "a" * 64 + "\n")])
def test_version_and_manifest_identity_validation(version: str, manifest: str) -> None:
    events, labels, reasons = inputs()
    with pytest.raises(ValueError):
        project_outcomes(events, labels, reasons, base_label_version_id=version, base_label_manifest_sha256=manifest)


def test_empty_events_retains_schema_and_input_calendar_unchanged() -> None:
    events, labels, reasons = inputs()
    result = project(events.iloc[:0], labels, reasons)
    assert result.empty
    assert set(events.columns).issubset(result.columns)
    assert {"effective_label", "event_main_eligible", "horizon"}.issubset(result.columns)
    assert reasons.isna().all()
    assert labels.label.eq("hit").all()


def test_final_calendar_day_has_empty_result_scope() -> None:
    events, labels, reasons = inputs()
    # Truncate at t0: known hit remains censored; there are no result rows.
    labels["calendar_full"], labels["main_eligible"] = False, False
    result = project(events, labels, reasons.iloc[:71])
    assert result.effective_label.eq("hit").all()
    assert not result.event_main_eligible.any()
    assert json.loads(result.result_scope_json.iloc[0]) == {"start": 71, "end": 70}
    assert np.array_equal(labels.horizon.to_numpy(), [20, 126])

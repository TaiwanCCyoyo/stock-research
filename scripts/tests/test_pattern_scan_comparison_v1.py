"""Hand-counted synthetic L1 four-cell contract, without market IO."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from jsonschema import Draft202012Validator, ValidationError

from research_core.pattern_scan_comparison_v1 import build_l1_comparison, comparison_json_schema


def _provenance() -> dict[str, Any]:
    return {
        "scope": "synthetic",
        "data_id": "SYNTH-data",
        "definition_id": "SYNTH-source",
        "code_commit": "SYNTH-code",
        "source_id": "SYNTH-source",
        "input_id": "SYNTH-input",
        "base_label_version_id": "SYNTH-labels",
        "base_label_manifest_sha256": "a" * 64,
        "generation": "SYNTH-generation",
        "actual_selected_stocks": ["SYNTH-0001", "SYNTH-0002", "SYNTH-0003"],
        "historical_exposed": True,
        "validation_scope": {
            "input_structure_verified": True,
            "full_q1_parity": False,
            "marginal_parity": False,
            "unseen_validation": False,
        },
    }


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    # One stock appears in two years: overall distinct stocks must not sum years.
    values = [
        ("0001", "2010-01-04", "hit", True, True, False),
        ("0001", "2011-01-04", "loss", True, True, False),
        ("0002", "2011-01-05", "flat-win", True, True, False),
        ("0002", "2012-01-04", "unknown", True, False, False),
        ("0003", "2012-01-05", "hit", False, False, False),
        ("0003", "2013-01-04", "unknown", False, False, False),
        ("0001", "2013-01-07", "loss", True, False, True),
        ("0001", "2014-01-06", "unknown", True, False, True),
    ]
    rows = [
        {
            "security_id": f"SYNTH-{code}",
            "event_id": f"synthetic-{i}",
            "t0": day,
            "pattern_id": "L1",
            "cohort_id": "union",
            "definition_id": "SYNTH-source",
            "input_id": "SYNTH-input",
            "base_label_version_id": "SYNTH-labels",
            "base_label_manifest_sha256": "a" * 64,
            "horizon": horizon,
            "effective_label": label,
            "calendar_full": full,
            "event_main_eligible": eligible,
            "event_eligibility_excluded": excluded,
        }
        for i, (code, day, label, full, eligible, excluded) in enumerate(values)
        for horizon in (126, 252)
    ]
    conditions = pd.DataFrame([
        {
            "event_id": f"synthetic-{i}",
            "G_bin": "150to200",
            "G_status": "known",
            "G_reason": None,
            "VOL_a_bin": "le070",
            "VOL_a_status": "known",
            "VOL_a_reason": None,
        }
        for i in range(len(values))
    ])
    return pd.DataFrame(rows), conditions


def test_manual_counts_null_zero_and_bounded_deterministic_references() -> None:
    events, conditions = _inputs()
    before_events, before_conditions = events.copy(deep=True), conditions.copy(deep=True)
    payload = build_l1_comparison(events, conditions, provenance=_provenance())
    assert payload["cohort"] == {"pattern_id": "L1", "cohort_id": "union", "horizons": [126, 252], "event_n": 8}
    expected = {
        "event_n": 8,
        "distinct_stock_n": 3,
        "known_n": 3,
        "hit_n": 1,
        "loss_n": 1,
        "flat_win_n": 1,
        "unknown_n": 3,
        "excluded_known_n": 1,
        "censored_n": 2,
        "full_eligibility_excluded_n": 2,
        "censored_eligibility_excluded_n": 0,
        "full_main_potential_n": 4,
        "censored_potential_n": 2,
        "hit_rate": 1 / 3,
        "loss_rate": 1 / 3,
        "full_calendar_hit_lower_bound": 0.25,
        "full_calendar_hit_upper_bound": 0.5,
        "censored_hit_lower_bound": 0.5,
        "censored_hit_upper_bound": 1.0,
    }
    for horizon in payload["horizons"]:
        assert horizon["cohort"].items() >= expected.items()
        cells = {row["cell_id"]: row for row in horizon["cells"]}
        selected = cells.pop("vol_le_0_7__g_ge_1_5")
        assert selected["summary"].items() >= expected.items()
        assert selected["evaluation_status"]["status"] == "not_evaluated"
        assert selected["evaluation_status"]["reason"] == "synthetic_only"
        assert 0 < len(selected["references"]) <= 3
        for reference in selected["references"]:
            assert reference["horizon"] == horizon["horizon"]
            assert reference["event_id"] in set(events.event_id)
        for cell in cells.values():
            assert cell["summary"]["event_n"] == 0
            assert cell["summary"]["hit_n"] == 0
            assert cell["summary"]["hit_rate"] is None
            assert cell["references"] == []
            assert cell["evaluation_status"]["status"] == "not_evaluated"
    reverse = build_l1_comparison(events.iloc[::-1], conditions.iloc[::-1], provenance=_provenance())
    assert reverse == payload
    pd.testing.assert_frame_equal(events, before_events)
    pd.testing.assert_frame_equal(conditions, before_conditions)


def test_missing_and_not_applicable_stay_in_disjoint_audit_cells() -> None:
    events, conditions = _inputs()
    conditions.loc[0, ["G_bin", "G_status", "G_reason"]] = [None, "feature_unknown", "missing_source"]
    conditions.loc[1, ["VOL_a_bin", "VOL_a_status", "VOL_a_reason"]] = [None, "not_applicable", "outside_cohort"]
    conditions.loc[2, ["G_bin", "G_status", "G_reason"]] = [None, "not_applicable", "outside_cohort"]
    conditions.loc[2, ["VOL_a_bin", "VOL_a_status", "VOL_a_reason"]] = [None, "feature_unknown", "missing_source"]
    payload = build_l1_comparison(events, conditions, provenance=_provenance())
    for horizon in payload["horizons"]:
        unavailable = {(row["G_status"], row["VOL_a_status"]): row["summary"]["event_n"] for row in horizon["unavailable"]}
        assert len(unavailable) == 8
        assert unavailable[("feature_unknown", "known")] == 1
        assert unavailable[("known", "not_applicable")] == 1
        assert unavailable[("not_applicable", "feature_unknown")] == 1
        assert sum(unavailable.values()) == 3
        assert sum(row["summary"]["event_n"] for row in horizon["cells"]) == 5
    assert payload["horizons"][0]["cells"] == [
        {**row, "references": [{**ref, "horizon": 126} for ref in row["references"]]} for row in payload["horizons"][1]["cells"]
    ]


@pytest.mark.parametrize(
    "invalid",
    [
        "duplicate",
        "missing_horizon",
        "wrong_t0",
        "wrong_pattern",
        "wrong_cohort",
        "missing_condition",
        "extra_condition",
        "duplicate_condition",
        "unknown_bin",
        "known_reason",
        "unknown_without_reason",
    ],
)
def test_invalid_event_or_condition_relations_fail_closed(invalid: str) -> None:
    events, conditions = _inputs()
    if invalid == "duplicate":
        events = pd.concat([events, events.iloc[:1]], ignore_index=True)
    elif invalid == "missing_horizon":
        events = events.iloc[1:]
    elif invalid == "wrong_t0":
        events.loc[0, "t0"] = "2010-01-05"
    elif invalid == "wrong_pattern":
        events.loc[0, "pattern_id"] = "L2"
    elif invalid == "wrong_cohort":
        events.loc[0, "cohort_id"] = "original"
    elif invalid == "missing_condition":
        conditions = conditions.iloc[1:]
    elif invalid == "extra_condition":
        conditions = pd.concat([conditions, conditions.iloc[:1].assign(event_id="extra")], ignore_index=True)
    elif invalid == "duplicate_condition":
        conditions = pd.concat([conditions, conditions.iloc[:1]], ignore_index=True)
    elif invalid == "unknown_bin":
        conditions.loc[0, "G_bin"] = "fake"
    elif invalid == "known_reason":
        conditions.loc[0, "G_reason"] = "missing_source"
    else:
        conditions.loc[0, ["G_status", "G_bin"]] = ["feature_unknown", None]
    with pytest.raises(ValueError):
        build_l1_comparison(events, conditions, provenance=_provenance())


@pytest.mark.parametrize("flag", ["full_q1_parity", "marginal_parity", "unseen_validation"])
def test_synthetic_cannot_claim_research_validation(flag: str) -> None:
    events, conditions = _inputs()
    provenance = deepcopy(_provenance())
    provenance["validation_scope"][flag] = True
    with pytest.raises(ValueError):
        build_l1_comparison(events, conditions, provenance=provenance)


def _source_provenance(scope: str) -> dict[str, Any]:
    provenance = _provenance()
    provenance["scope"] = scope
    if scope == "full":
        provenance["validation_scope"].update(full_q1_parity=True, marginal_parity=True)
    return provenance


@pytest.mark.parametrize("scope", ["synthetic", "full"])
@pytest.mark.parametrize("column", ["definition_id", "input_id", "base_label_version_id", "base_label_manifest_sha256"])
def test_different_events_cannot_mix_source_cohorts(scope: str, column: str) -> None:
    events, conditions = _inputs()
    # Both rows of one event agree. This reproduces mixed cohorts that passed
    # the older check which considered each event's two horizons in isolation.
    events.loc[events.event_id.eq("synthetic-1"), column] = "b" * 64 if column.endswith("sha256") else "SYNTH-other-source"
    assert bool(events.groupby("event_id")[column].nunique().eq(1).all())
    assert events[column].nunique() == 2
    with pytest.raises(ValueError):
        build_l1_comparison(events, conditions, provenance=_source_provenance(scope))


@pytest.mark.parametrize("scope", ["synthetic", "full"])
@pytest.mark.parametrize("field", ["definition_id", "source_id", "input_id", "base_label_version_id", "base_label_manifest_sha256"])
def test_provenance_cannot_claim_a_source_other_than_event_rows(scope: str, field: str) -> None:
    events, conditions = _inputs()
    provenance = _source_provenance(scope)
    provenance[field] = "b" * 64 if field.endswith("sha256") else "SYNTH-other-source"
    with pytest.raises(ValueError):
        build_l1_comparison(events, conditions, provenance=provenance)


@pytest.mark.parametrize("column", ["definition_id", "input_id", "base_label_version_id", "base_label_manifest_sha256"])
@pytest.mark.parametrize("invalid", ["missing", "null", "blank"])
def test_event_source_fields_are_required_known_and_nonblank(column: str, invalid: str) -> None:
    events, conditions = _inputs()
    if invalid == "missing":
        events = events.drop(columns=column)
    else:
        events.loc[events.event_id.eq("synthetic-1"), column] = None if invalid == "null" else " "
    with pytest.raises(ValueError):
        build_l1_comparison(events, conditions, provenance=_provenance())


@pytest.mark.parametrize("manifest", ["a" * 63, "z" * 64, "A" * 64, "a" * 64 + "\n"])
def test_matching_but_invalid_manifest_does_not_establish_source_identity(manifest: str) -> None:
    events, conditions = _inputs()
    events["base_label_manifest_sha256"] = manifest
    provenance = _provenance()
    provenance["base_label_manifest_sha256"] = manifest
    with pytest.raises(ValueError):
        build_l1_comparison(events, conditions, provenance=provenance)


@pytest.mark.parametrize("scope", ["synthetic", "full"])
def test_same_source_multiple_stocks_and_both_horizons_remain_valid(scope: str) -> None:
    events, conditions = _inputs()
    provenance = _source_provenance(scope)
    payload = build_l1_comparison(events, conditions, provenance=provenance)
    Draft202012Validator(comparison_json_schema()).validate(payload)
    assert payload["cohort"]["event_n"] == 8
    assert payload["provenance"] == provenance
    for horizon in payload["horizons"]:
        assert horizon["cohort"]["distinct_stock_n"] == 3
        assert horizon["cohort"]["event_n"] == 8


def test_empty_cohort_with_selected_zero_event_stocks_retains_valid_schema() -> None:
    events, conditions = _inputs()
    provenance = _provenance()
    payload = build_l1_comparison(events.iloc[:0], conditions.iloc[:0], provenance=provenance)
    Draft202012Validator(comparison_json_schema()).validate(payload)
    assert payload["provenance"] == provenance
    assert payload["cohort"]["event_n"] == 0
    assert [row["horizon"] for row in payload["horizons"]] == [126, 252]
    for horizon in payload["horizons"]:
        assert horizon["cohort"]["event_n"] == horizon["cohort"]["distinct_stock_n"] == 0
        assert horizon["cohort"]["hit_rate"] is None
        assert all(cell["summary"]["event_n"] == 0 and cell["references"] == [] for cell in horizon["cells"])


def test_exported_fixture_schema_evaluation_state_and_hand_counts() -> None:
    path = Path(__file__).parent / "fixtures" / "l1-volume-comparison.synthetic.v1.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(comparison_json_schema()).validate(payload)
    assert payload["synthetic"] is True
    assert payload["cohort"]["event_n"] == 8
    first, second = payload["horizons"]
    assert [first["horizon"], second["horizon"]] == [126, 252]
    assert {key: first["cohort"][key] for key in ("event_n", "known_n", "hit_n", "loss_n", "flat_win_n", "unknown_n", "censored_n")} == {
        "event_n": 8,
        "known_n": 4,
        "hit_n": 1,
        "loss_n": 2,
        "flat_win_n": 1,
        "unknown_n": 4,
        "censored_n": 2,
    }
    assert {key: second["cohort"][key] for key in ("event_n", "known_n", "hit_n", "loss_n", "flat_win_n", "unknown_n", "censored_n")} == {
        "event_n": 8,
        "known_n": 4,
        "hit_n": 0,
        "loss_n": 2,
        "flat_win_n": 2,
        "unknown_n": 3,
        "censored_n": 3,
    }
    for horizon in payload["horizons"]:
        for cell in [*horizon["cells"], *horizon["unavailable"]]:
            assert cell["evaluation_status"] == {"status": "not_evaluated", "reason": "synthetic_only"}
            assert len(cell["references"]) <= 3


@pytest.mark.parametrize("invalid", ["reference_bound", "horizon_order", "synthetic_claim"])
def test_exported_contract_rejects_structural_misrepresentation(invalid: str) -> None:
    events, conditions = _inputs()
    payload = build_l1_comparison(events, conditions, provenance=_provenance())
    if invalid == "reference_bound":
        references = payload["horizons"][0]["cells"][0]["references"]
        references.append(deepcopy(references[0]))
    elif invalid == "horizon_order":
        payload["horizons"].reverse()
    else:
        payload["synthetic"] = False
    with pytest.raises(ValidationError):
        Draft202012Validator(comparison_json_schema()).validate(payload)

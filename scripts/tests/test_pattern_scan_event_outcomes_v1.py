from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest

from research_core.artifact_store import object_digest
from research_core.pattern_scan_event_outcomes_v1 import BaseOutcome, EventIdentity, Label, LabelReference, apply_event_overlay


def _base(horizon: int = 126) -> BaseOutcome:
    return BaseOutcome(LabelReference("2330", "2010-01-04", horizon, "labels-v1"), "hit", True, True)


def _event(pattern: str = "B1") -> EventIdentity:
    return EventIdentity("2330", "2010-01-04", pattern, "original", "definition-v1", "input-v1")


def test_same_base_different_lookbacks_keep_independent_denominators() -> None:
    base = _base()
    original, original_hash = replace(base), hash(base)
    b1 = apply_event_overlay(base, _event(), detection_quality_reasons=("lookback_jump",))
    l1 = apply_event_overlay(base, _event("L1"))
    outcomes = {row.key: row for row in (b1, l1)}
    assert len(outcomes) == 2
    assert (b1.base_label, l1.base_label) == ("hit", "hit")
    assert (b1.effective_label, b1.event_main_eligible) == ("unknown", False)
    assert (l1.effective_label, l1.event_main_eligible) == ("hit", True)
    summary = {pattern: sum(row.effective_known and row.event_main_eligible for row in rows) for pattern, rows in {"B1": [b1], "L1": [l1]}.items()}
    assert summary == {"B1": 0, "L1": 1}
    assert base == original and hash(base) == original_hash
    with pytest.raises(FrozenInstanceError):
        setattr(base, "label", "unknown")


def test_event_identity_reuses_digest_and_separates_horizons_and_definitions() -> None:
    event = _event()
    assert event.event_id == object_digest({
        "security_id": "2330",
        "t0": "2010-01-04",
        "pattern_id": "B1",
        "subtype_id": "original",
        "definition_id": "definition-v1",
        "input_id": "input-v1",
    })
    assert apply_event_overlay(_base(126), event).key != apply_event_overlay(_base(252), event).key
    for field in ("subtype_id", "definition_id", "input_id"):
        assert replace(event, **{field: "another"}).event_id != event.event_id


def test_unknown_censored_hit_and_eligibility_only_semantics() -> None:
    unknown = BaseOutcome(_base().reference, "unknown", True, False, "missing_price")
    projected = apply_event_overlay(unknown, _event())
    assert not projected.base_known and not projected.effective_known
    assert projected.effective_unknown_reasons == ("base:missing_price",)
    censored = BaseOutcome(_base().reference, "hit", False, False)
    row = apply_event_overlay(censored, _event())
    assert row.effective_label == "hit" and row.base_known and not row.event_main_eligible
    excluded = apply_event_overlay(_base(), _event(), event_eligibility_reasons=["not_in_universe"])
    assert excluded.effective_label == "hit" and excluded.effective_known and not excluded.event_main_eligible
    assert excluded.effective_unknown_reasons == ()


def test_reasons_canonicalized_without_losing_scope_or_base_unknown() -> None:
    base = BaseOutcome(_base().reference, "unknown", False, False, "same")
    row = apply_event_overlay(
        base,
        _event(),
        detection_quality_reasons=["z", "same", "z"],
        result_quality_reasons=(value for value in ["same", "a"]),
        event_eligibility_reasons=["z", "a", "z"],
    )
    assert row.detection_quality_reasons == ("same", "z")
    assert row.result_quality_reasons == ("a", "same")
    assert row.event_eligibility_reasons == ("a", "z")
    assert row.effective_unknown_reasons == ("base:same", "detection:same", "detection:z", "result:a", "result:same")
    assert base.unknown_reason == "same"


@pytest.mark.parametrize("field", ["detection_quality_reasons", "result_quality_reasons", "event_eligibility_reasons"])
@pytest.mark.parametrize("values", ["jump", [""], ["  "], [123]])
def test_invalid_reason_inputs_fail(field: str, values: object) -> None:
    with pytest.raises(ValueError, match="reason"):
        apply_event_overlay(_base(), _event(), **{field: cast(tuple[str, ...], values)})


@pytest.mark.parametrize("field,value", [("security_id", "other"), ("t0", "2010-01-05")])
def test_mismatched_event_fails(field: str, value: str) -> None:
    with pytest.raises(ValueError, match="match"):
        apply_event_overlay(_base(), replace(_event(), **{field: value}))


@pytest.mark.parametrize("horizon", [0, -1, True, 1.5])
def test_invalid_horizon_fails(horizon: int) -> None:
    with pytest.raises(ValueError, match="horizon"):
        LabelReference("2330", "2010-01-04", horizon, "v1")


@pytest.mark.parametrize("t0", ["20100104", "2010-1-4", "2010-02-30", "", "2010-01-04T00:00:00"])
def test_noncanonical_date_fails(t0: str) -> None:
    with pytest.raises(ValueError):
        LabelReference("2330", t0, 126, "v1")


@pytest.mark.parametrize("field", ["security_id", "pattern_id", "subtype_id", "definition_id", "input_id"])
def test_blank_event_identity_fails(field: str) -> None:
    with pytest.raises(ValueError, match="nonblank"):
        replace(_event(), **{field: " "})


def test_blank_version_fails() -> None:
    with pytest.raises(ValueError, match="version_id"):
        replace(_base().reference, version_id=" ")


@pytest.mark.parametrize(
    "label,full,eligible,reason",
    [
        ("unknown", True, True, "missing"),
        ("unknown", True, False, None),
        ("hit", True, True, "missing"),
        ("hit", False, True, None),
        ("hit", True, False, None),
        ("bogus", True, True, None),
        ("unknown", True, False, " "),
    ],
)
def test_invalid_base_states_fail(label: str, full: bool, eligible: bool, reason: str | None) -> None:
    with pytest.raises(ValueError):
        BaseOutcome(_base().reference, cast(Label, label), full, eligible, reason)


@pytest.mark.parametrize("label", ["loss", "flat-win"])
def test_other_known_labels_preserved(label: Label) -> None:
    row = apply_event_overlay(replace(_base(), label=label), _event())
    assert row.effective_label == label and row.event_main_eligible

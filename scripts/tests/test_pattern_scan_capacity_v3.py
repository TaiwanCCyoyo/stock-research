"""Synthetic phase-only disk admission; no producer or market computation."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_core import pattern_scan_capacity_v3 as capacity
from research_core.artifact_store import file_digest, write_json


@pytest.fixture(params=("prepare", "stock"))
def supplied(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = tmp_path / "resource-profile.json"
    write_json(profile, {"synthetic": True})
    phase = request.param
    plan = {
        "schema": capacity.SCHEMA,
        "phase": phase,
        "publication_policy": capacity.POLICY,
        "source_id": "synthetic-source",
        "input_id": "synthetic-input",
        "profile": {"path": str(profile), "bytes": profile.stat().st_size, "sha256": file_digest(profile)},
        "geometry": {"calendar_n": 4110, "ordinary_reference_n": 1942},
        "components": {
            name: {
                "estimated_bytes": 100 if name == capacity.PHASE_COMPONENTS[phase][0] else 0,
                "evidence": "synthetic measurement; existing shared bytes are already allocated",
            }
            for name in capacity.PHASE_COMPONENTS[phase]
        },
        "reserve_bytes": 32 * 1024**3,
    }
    arguments = {
        "phase": phase,
        "source_id": "synthetic-source",
        "input_id": "synthetic-input",
        "profile_path": profile,
        "available_bytes": plan["reserve_bytes"] + 100,
    }
    return plan, arguments


def test_exact_phase_budget_admits_only_this_phase(supplied: Any) -> None:
    plan, arguments = supplied
    original = deepcopy(plan)
    result = capacity.assess_phase_capacity(plan, **arguments)
    assert result["sufficient"] is True
    assert result["phase"] == plan["phase"] and result["phase_only"] is True
    assert result["full_study_admitted"] is False
    assert result["known_estimate_bytes"] == 100
    assert result["required_bytes"] == plan["reserve_bytes"] + 100
    assert result["available_bytes"] == result["required_bytes"]
    assert plan == original


def test_one_byte_short_is_insufficient_without_losing_phase_scope(supplied: Any) -> None:
    plan, arguments = supplied
    arguments["available_bytes"] -= 1
    result = capacity.assess_phase_capacity(plan, **arguments)
    assert result["sufficient"] is False and result["full_study_admitted"] is False
    assert result["required_bytes"] == plan["reserve_bytes"] + 100


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("schema", "pattern-scan-capacity.v2"),
        ("phase", "all"),
        ("publication_policy", "legacy"),
        ("source_id", "different"),
        ("source_id", None),
        ("input_id", "different"),
        ("input_id", ""),
        ("reserve_bytes", 31 * 1024**3),
        ("reserve_bytes", True),
        ("reserve_bytes", None),
        ("reserve_bytes", -1),
        ("reserve_bytes", float(32 * 1024**3)),
    ),
)
def test_invalid_plan_identity_policy_or_reserve_rejected(supplied: Any, field: str, value: Any) -> None:
    plan, arguments = supplied
    plan[field] = value
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("phase", "all"),
        ("phase", "profile"),
        ("phase", None),
        ("phase", []),
        ("source_id", ""),
        ("source_id", "  "),
        ("source_id", None),
        ("input_id", ""),
        ("input_id", None),
        ("input_id", False),
        ("available_bytes", -1),
        ("available_bytes", True),
        ("available_bytes", None),
        ("available_bytes", 1.0),
    ),
)
def test_invalid_admission_arguments_fail_closed(supplied: Any, field: str, value: Any) -> None:
    plan, arguments = supplied
    arguments[field] = value
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)


@pytest.mark.parametrize("change", ("missing", "extra", "other-phase", "none", "shared_existing"))
def test_exact_phase_components_required(supplied: Any, change: str) -> None:
    plan, arguments = supplied
    components = plan["components"]
    if change == "missing":
        del components["retained_staging"]
    elif change == "extra":
        components["followup_observations"] = {"estimated_bytes": 0, "evidence": "not this phase"}
    elif change == "other-phase":
        del components[capacity.PHASE_COMPONENTS[plan["phase"]][0]]
        name = "stock_checkpoints" if plan["phase"] == "prepare" else "prepared_prices"
        components[name] = {"estimated_bytes": 100, "evidence": "different phase"}
    elif change == "none":
        plan["components"] = None
    else:
        components["shared_existing"] = {"estimated_bytes": 0, "evidence": "existing allocation is not a new component"}
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)


@pytest.mark.parametrize("component", ("phase_metadata", "retained_staging"))
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("estimated_bytes", None),
        ("estimated_bytes", True),
        ("estimated_bytes", -1),
        ("estimated_bytes", 0.0),
        ("estimated_bytes", "unknown"),
        ("evidence", ""),
        ("evidence", " \n"),
        ("evidence", None),
    ),
)
def test_zero_components_still_need_integer_estimates_and_evidence(supplied: Any, component: str, field: str, value: Any) -> None:
    plan, arguments = supplied
    plan["components"][component][field] = value
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)


@pytest.mark.parametrize(
    "geometry",
    (
        {},
        {"calendar_n": 4110, "ordinary_reference_n": 4},
        {"calendar_n": 4110.0, "ordinary_reference_n": 1942},
        {"calendar_n": 4110, "ordinary_reference_n": True},
        {"calendar_n": 4110, "ordinary_reference_n": 1942, "extra": 1},
        None,
    ),
)
def test_full_fixed_geometry_is_required_even_for_phase_only(supplied: Any, geometry: Any) -> None:
    plan, arguments = supplied
    plan["geometry"] = geometry
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)


@pytest.mark.parametrize("change", ("changed-bytes", "missing", "hash", "size", "bool-size", "relative", "different-path", "missing-field", "alias"))
def test_profile_descriptor_matches_current_physical_file(supplied: Any, tmp_path: Path, change: str) -> None:
    plan, arguments = supplied
    profile = arguments["profile_path"]
    if change == "changed-bytes":
        profile.write_bytes(b"x" * profile.stat().st_size)
    elif change == "missing":
        profile.unlink()
    elif change == "hash":
        plan["profile"]["sha256"] = "0" * 64
    elif change == "size":
        plan["profile"]["bytes"] += 1
    elif change == "bool-size":
        plan["profile"]["bytes"] = True
    elif change == "relative":
        plan["profile"]["path"] = profile.name
        arguments["profile_path"] = Path(profile.name)
    elif change == "different-path":
        other = tmp_path / "different-profile.json"
        other.write_bytes(profile.read_bytes())
        arguments["profile_path"] = other
    elif change == "missing-field":
        del plan["profile"]["sha256"]
    else:
        alias = tmp_path / "hardlink-profile.json"
        os.link(profile, alias)
        plan["profile"]["path"] = str(alias)
        arguments["profile_path"] = alias
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)


def test_phase_plan_cannot_claim_full_study_or_silently_accept_combined_plan(supplied: Any) -> None:
    plan, arguments = supplied
    plan["full_study_admitted"] = True
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)
    del plan["full_study_admitted"]
    plan["phase"] = ["prepare", "stock"]
    with pytest.raises(ValueError):
        capacity.assess_phase_capacity(plan, **arguments)


@pytest.mark.parametrize("sufficient", (True, False))
def test_require_uses_current_free_space(supplied: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sufficient: bool) -> None:
    plan, arguments = supplied
    path = tmp_path / "phase-capacity.json"
    write_json(path, plan)
    free = arguments.pop("available_bytes") - (0 if sufficient else 1)
    observed = []

    def disk_usage(primary: Path) -> SimpleNamespace:
        observed.append(primary)
        return SimpleNamespace(free=free)

    monkeypatch.setattr(capacity.shutil, "disk_usage", disk_usage)
    if sufficient:
        result = capacity.require_phase_capacity(path, tmp_path, **arguments)
        assert result["sufficient"] is True and result["full_study_admitted"] is False
    else:
        with pytest.raises(ValueError, match="phase capacity is not established"):
            capacity.require_phase_capacity(path, tmp_path, **arguments)
    assert observed == [tmp_path]


def test_missing_plan_cannot_bypass_admission(supplied: Any, tmp_path: Path) -> None:
    _, arguments = supplied
    arguments.pop("available_bytes")
    with pytest.raises(ValueError, match="phase capacity plan required"):
        capacity.require_phase_capacity(None, tmp_path, **arguments)  # type: ignore[arg-type]

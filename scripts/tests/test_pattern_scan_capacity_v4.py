"""Synthetic continuation admission; no producer, calculation or owned job."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_core import pattern_scan_capacity_v4 as capacity
from research_core.artifact_store import canonical, file_digest, write_json

GIB = 1024**3


@pytest.fixture(params=("prices", "barrier", "analysis"))
def supplied(tmp_path: Path, request: pytest.FixtureRequest) -> dict[str, Any]:
    run = tmp_path / "run"
    run.mkdir()
    evidence = tmp_path / "observation.json"
    write_json(evidence, {"synthetic_observation": True})
    phase = request.param
    components = {
        name: {"estimated_bytes": 100 if position == 0 else 0, "evidence": "synthetic incremental allocation; existing/shared bytes excluded"}
        for position, name in enumerate(capacity.PHASE_COMPONENTS[phase])
    }
    plan = {
        "schema": capacity.SCHEMA,
        "phase": phase,
        "executor_source_id": "current-executor",
        "ancestral_source_id": "original-source",
        "input_id": "original-input",
        "geometry": {"calendar_n": 4110, "ordinary_reference_n": 1942},
        "components": components,
        "memory": {
            "estimated_peak_bytes": 2 * GIB,
            "job_limit_bytes": 3 * GIB,
            "host_reserve_bytes": 4 * GIB,
            "evidence": "synthetic observed bounded peak with explicit job and host headroom",
        },
        "reserve_bytes": 32 * GIB,
        "evidence": [{"path": str(evidence), "bytes": evidence.stat().st_size, "sha256": file_digest(evidence), "role": "synthetic resource observation"}],
    }
    path = tmp_path / "capacity.json"
    write_json(path, plan)
    arguments = {
        "phase": phase,
        "executor": {"source_id": "current-executor"},
        "source_id": "original-source",
        "input_id": "original-input",
        "available_disk_bytes": 32 * GIB + 100,
        "available_memory_bytes": 7 * GIB,
    }
    return {"plan": plan, "path": path, "arguments": arguments, "run": run, "evidence": evidence}


def _require(case: dict[str, Any]) -> dict[str, Any]:
    args = case["arguments"]
    return capacity.require_continuation_capacity(
        case["path"], run=case["run"], phase=args["phase"], executor=args["executor"], source_id=args["source_id"], input_id=args["input_id"]
    )


def _resources(case: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capacity.shutil, "disk_usage", lambda location: SimpleNamespace(free=case["arguments"]["available_disk_bytes"]))
    monkeypatch.setattr(capacity, "host_resources", lambda: {"physical_available_bytes": case["arguments"]["available_memory_bytes"]})


def test_exact_thresholds_admit_only_requested_phase_without_mutation(supplied: dict[str, Any]) -> None:
    original = deepcopy(supplied["plan"])
    result = capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])
    assert result["phase"] == supplied["arguments"]["phase"] and result["phase_only"] is True
    assert result["full_study_admitted"] is False and result["sufficient"] is True
    assert result["executor_source_id"] == "current-executor" and result["ancestral_source_id"] == "original-source"
    assert result["disk"] == {
        "additional_estimate_bytes": 100,
        "reserve_bytes": 32 * GIB,
        "required_bytes": 32 * GIB + 100,
        "available_bytes": 32 * GIB + 100,
        "sufficient": True,
    }
    assert result["memory"] == {
        "estimated_peak_bytes": 2 * GIB,
        "job_limit_bytes": 3 * GIB,
        "host_reserve_bytes": 4 * GIB,
        "required_bytes": 7 * GIB,
        "available_bytes": 7 * GIB,
        "sufficient": True,
    }
    assert supplied["plan"] == original


def test_assess_is_pure_and_does_not_verify_files_or_probe_resources(supplied: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("pure assessment must not touch filesystem/resources")

    for name in ("describe_file", "read_json", "checked_path", "host_resources"):
        monkeypatch.setattr(capacity, name, forbidden)
    monkeypatch.setattr(capacity.shutil, "disk_usage", forbidden)
    assert capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])["sufficient"] is True


@pytest.mark.parametrize("resource", ["disk", "memory"])
def test_one_byte_short_refuses_only_this_phase_with_separate_resource_results(supplied: dict[str, Any], resource: str) -> None:
    supplied["arguments"][f"available_{resource}_bytes"] -= 1
    result = capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])
    assert result["sufficient"] is False and result["full_study_admitted"] is False
    assert result[resource]["sufficient"] is False
    assert result["memory" if resource == "disk" else "disk"]["sufficient"] is True


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("schema", "legacy"),
        ("phase", "all"),
        ("executor_source_id", "original-source"),
        ("ancestral_source_id", "current-executor"),
        ("input_id", "another-input"),
        ("reserve_bytes", 32 * GIB - 1),
        ("reserve_bytes", True),
        ("reserve_bytes", None),
        ("reserve_bytes", float(32 * GIB)),
    ],
)
def test_wrong_plan_identity_or_reserve_rejected(supplied: dict[str, Any], key: str, value: Any) -> None:
    supplied["plan"][key] = value
    with pytest.raises(ValueError):
        capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("phase", "stock"),
        ("phase", ["prices", "barrier"]),
        ("executor", None),
        ("executor", {}),
        ("executor", {"source_id": " "}),
        ("source_id", None),
        ("input_id", False),
        ("available_disk_bytes", None),
        ("available_disk_bytes", True),
        ("available_disk_bytes", -1),
        ("available_memory_bytes", None),
        ("available_memory_bytes", 7.0),
        ("available_memory_bytes", False),
    ],
)
def test_unknown_or_malformed_admission_arguments_rejected(supplied: dict[str, Any], key: str, value: Any) -> None:
    supplied["arguments"][key] = value
    with pytest.raises(ValueError):
        capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])


@pytest.mark.parametrize("damage", ["missing", "other_phase", "existing_shared", "full_study", "geometry_float", "geometry_bool", "geometry_small"])
def test_exact_phase_scope_and_full_geometry_required(supplied: dict[str, Any], damage: str) -> None:
    plan = supplied["plan"]
    first = capacity.PHASE_COMPONENTS[plan["phase"]][0]
    if damage == "missing":
        plan["components"].pop(first)
    elif damage == "other_phase":
        plan["components"] = {"not_this_phase": {"estimated_bytes": 0, "evidence": "synthetic"}}
    elif damage == "existing_shared":
        plan["components"]["shared_existing"] = {"estimated_bytes": 1, "evidence": "already allocated"}
    elif damage == "full_study":
        plan["full_study_admitted"] = True
    elif damage == "geometry_float":
        plan["geometry"]["calendar_n"] = 4110.0
    elif damage == "geometry_bool":
        plan["geometry"]["ordinary_reference_n"] = True
    else:
        plan["geometry"]["ordinary_reference_n"] = 4
    with pytest.raises(ValueError):
        capacity.assess_continuation_capacity(plan, **supplied["arguments"])


@pytest.mark.parametrize(
    ("key", "value"),
    [("estimated_bytes", None), ("estimated_bytes", True), ("estimated_bytes", -1), ("estimated_bytes", 1.0), ("evidence", ""), ("evidence", None)],
)
def test_additional_component_numbers_and_zero_estimate_evidence_are_explicit(supplied: dict[str, Any], key: str, value: Any) -> None:
    first = capacity.PHASE_COMPONENTS[supplied["plan"]["phase"]][0]
    supplied["plan"]["components"][first][key] = value
    with pytest.raises(ValueError):
        capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("estimated_peak_bytes", 0),
        ("estimated_peak_bytes", None),
        ("estimated_peak_bytes", True),
        ("estimated_peak_bytes", 3 * GIB),
        ("job_limit_bytes", 2 * GIB),
        ("job_limit_bytes", 8 * GIB + 1),
        ("job_limit_bytes", float(3 * GIB)),
        ("host_reserve_bytes", 4 * GIB - 1),
        ("host_reserve_bytes", False),
        ("evidence", " \n"),
    ],
)
def test_peak_job_limit_and_host_reserve_are_independently_bounded(supplied: dict[str, Any], key: str, value: Any) -> None:
    supplied["plan"]["memory"][key] = value
    with pytest.raises(ValueError):
        capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])


@pytest.mark.parametrize("damage", ["empty", "relative", "traversal", "bytes_bool", "bytes_null", "hash", "role", "extra"])
def test_evidence_descriptor_shape_fails_closed_without_reading_payload(supplied: dict[str, Any], damage: str) -> None:
    descriptor = supplied["plan"]["evidence"][0]
    if damage == "empty":
        supplied["plan"]["evidence"] = []
    elif damage == "relative":
        descriptor["path"] = "relative.json"
    elif damage == "traversal":
        descriptor["path"] = str(supplied["evidence"].parent / ".." / "escape.json")
    elif damage == "bytes_bool":
        descriptor["bytes"] = True
    elif damage == "bytes_null":
        descriptor["bytes"] = None
    elif damage == "hash":
        descriptor["sha256"] = "unknown"
    elif damage == "role":
        descriptor["role"] = " "
    else:
        descriptor["extra"] = "not registered"
    with pytest.raises(ValueError):
        capacity.assess_continuation_capacity(supplied["plan"], **supplied["arguments"])


def test_require_verifies_current_resources_and_unique_physical_evidence_once(supplied: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    _resources(supplied, monkeypatch)
    supplied["plan"]["evidence"].append({**supplied["plan"]["evidence"][0], "role": "same pin used by another estimate"})
    supplied["path"].write_bytes(canonical(supplied["plan"]))
    describe_file = capacity.describe_file
    calls: list[Path] = []

    def observed(root: Path, path: Path) -> dict[str, Any]:
        calls.append(path)
        return describe_file(root, path)

    monkeypatch.setattr(capacity, "describe_file", observed)
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in (supplied["path"], supplied["evidence"])}
    assert _require(supplied)["sufficient"] is True
    assert calls == [supplied["evidence"]]
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in before}
    assert not list(supplied["run"].iterdir())


@pytest.mark.parametrize("damage", ["missing", "modified", "size", "digest", "alias", "conflicting_duplicate"])
def test_require_refuses_missing_modified_or_aliased_pinned_evidence(
    supplied: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, damage: str
) -> None:
    _resources(supplied, monkeypatch)
    descriptor = supplied["plan"]["evidence"][0]
    if damage == "missing":
        supplied["evidence"].unlink()
    elif damage == "modified":
        supplied["evidence"].write_bytes(b"x" * descriptor["bytes"])
    elif damage == "size":
        descriptor["bytes"] += 1
    elif damage == "digest":
        descriptor["sha256"] = "0" * 64
    elif damage == "alias":
        os.link(supplied["evidence"], tmp_path / "alias.json")
    else:
        supplied["plan"]["evidence"].append({**descriptor, "sha256": "0" * 64})
    supplied["path"].write_bytes(canonical(supplied["plan"]))
    with pytest.raises(ValueError, match="evidence|hardlink"):
        _require(supplied)
    assert not list(supplied["run"].iterdir())


@pytest.mark.parametrize("resource", ["disk", "memory"])
def test_require_insufficient_resource_reports_pending_phase_without_admission(
    supplied: dict[str, Any], monkeypatch: pytest.MonkeyPatch, resource: str
) -> None:
    supplied["arguments"][f"available_{resource}_bytes"] -= 1
    _resources(supplied, monkeypatch)
    with pytest.raises(ValueError, match=f"pending_phase={supplied['arguments']['phase']}"):
        _require(supplied)
    assert not list(supplied["run"].iterdir())


@pytest.mark.parametrize("field", ["path", "run"])
def test_require_refuses_relative_locations_before_resource_probe(supplied: dict[str, Any], monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("invalid path must be rejected before resource probes")

    monkeypatch.setattr(capacity.shutil, "disk_usage", forbidden)
    monkeypatch.setattr(capacity, "host_resources", forbidden)
    supplied[field] = Path("relative")
    with pytest.raises(ValueError, match="absolute"):
        _require(supplied)

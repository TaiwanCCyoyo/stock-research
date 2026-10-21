"""Synthetic metadata-only loader tests; resource validator is explicitly mocked."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from research_core import pattern_scan_profile_observation_v3 as observation
from research_core.artifact_store import canonical, file_digest, object_digest, write_json


def _source(commit: str) -> dict[str, Any]:
    body = {
        "schema": "pattern-scan-source.git.v2",
        "code": {"commit": commit * 40, "dirty": True},
        "runtime": {"python": "synthetic", "pandas": "synthetic"},
        "platform": "synthetic-platform",
        "numerical_thread_limits": {"OMP_NUM_THREADS": "1"},
    }
    return {**body, "source_id": object_digest(body)}


@pytest.fixture
def packet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    historical_source, current_source = _source("a"), _source("b")
    historical = {
        "schema": "pattern-scan-resource-profile.v1",
        "source_id": historical_source["source_id"],
        "input_id": "historical-input",
        # This is a reader fixture, not proof of a valid resource profile.
        "selected": {"workers": 2, "memory_cap_bytes": 6 * 1024**3, "stocks_per_process": 1},
    }
    path = tmp_path / "historical" / "resource-profile.json"
    path.parent.mkdir()
    write_json(path, historical)
    preparation = {"schema": "pattern-scan-derived-preparation.v2", "source": historical_source, "input_id": historical["input_id"]}
    preparation_path = path.parent / "derived-preparation.json"
    write_json(preparation_path, preparation)
    wrapper = {
        "schema": observation.SCHEMA,
        "current_source_id": current_source["source_id"],
        "current_input_id": "current-input",
        "geometry": {"calendar_n": 4110, "ordinary_reference_n": 1942},
        "historical_profile": {"path": str(path), "bytes": path.stat().st_size, "sha256": file_digest(path)},
        "historical_source": historical_source,
        "selected": deepcopy(historical["selected"]),
        "advisory_resource_observation_only": True,
        "current_performance_proven": False,
        "reuses_numerical_payload": False,
    }
    wrapper_path = tmp_path / "observation.json"
    write_json(wrapper_path, wrapper)

    def validate(profile: dict[str, Any], *, source: dict[str, Any], input_id: str) -> None:
        # No actual resource artifacts/runtime/Git/producer are inspected. The
        # real validator owns those checks; here we exercise argument routing.
        if (
            profile.get("schema") != "pattern-scan-resource-profile.v1"
            or profile.get("source_id") != source["source_id"]
            or profile.get("input_id") != input_id
        ):
            raise ValueError("mock validator source/input mismatch")

    validator = Mock(side_effect=validate)
    monkeypatch.setattr(observation, "validate_profile", validator)
    return {
        "source": current_source,
        "historical_source": historical_source,
        "historical": historical,
        "path": path,
        "wrapper": wrapper,
        "wrapper_path": wrapper_path,
        "preparation": preparation,
        "preparation_path": preparation_path,
        "validator": validator,
    }


def _load(packet: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return observation.load_execution_profile(
        packet["wrapper_path"],
        source=packet["source"],
        input_id="current-input",
        calendar_n=kwargs.get("calendar_n", 4110),
        ordinary_reference_n=kwargs.get("ordinary_reference_n", 1942),
    )


def _rewrite(packet: dict[str, Any], name: str) -> None:
    packet[f"{name}_path"].write_bytes(canonical(packet[name]))


def test_historical_observation_preserves_identity_selected_and_physical_inputs(packet: dict[str, Any]) -> None:
    paths = [packet[key] for key in ("path", "preparation_path", "wrapper_path")]
    before = {path: (file_digest(path), path.stat().st_mtime_ns) for path in paths}
    actual = _load(packet)
    packet["validator"].assert_called_once_with(packet["historical"], source=packet["historical_source"], input_id="historical-input")
    assert {key: value for key, value in actual.items() if key != "observation_provenance"} == packet["historical"]
    assert actual["source_id"] != packet["source"]["source_id"]
    assert actual["input_id"] == "historical-input"
    provenance = actual["observation_provenance"]
    assert provenance["historical_profile"] == packet["wrapper"]["historical_profile"]
    assert provenance["historical_source"] == packet["historical_source"]
    assert provenance["current_source_id"] == packet["source"]["source_id"]
    assert provenance["current_input_id"] == "current-input"
    assert provenance["advisory_resource_observation_only"] is True
    assert provenance["current_performance_proven"] is False
    assert provenance["reuses_numerical_payload"] is False
    assert before == {path: (file_digest(path), path.stat().st_mtime_ns) for path in paths}


def test_current_v1_profile_routes_directly_through_existing_validator(packet: dict[str, Any]) -> None:
    path = packet["wrapper_path"].parent / "current-profile.json"
    current = {**packet["historical"], "source_id": packet["source"]["source_id"], "input_id": "current-input"}
    write_json(path, current)
    assert observation.load_execution_profile(path, source=packet["source"], input_id="current-input", calendar_n=4110, ordinary_reference_n=1942) == current
    packet["validator"].assert_called_once_with(current, source=packet["source"], input_id="current-input")
    with pytest.raises(ValueError, match="source/input"):
        observation.load_execution_profile(path, source=packet["source"], input_id="changed-input", calendar_n=4110, ordinary_reference_n=1942)


@pytest.mark.parametrize(
    ("keys", "value"),
    [
        (("schema",), "unknown"),
        (("current_source_id",), "changed-source"),
        (("current_input_id",), "changed-input"),
        (("geometry", "calendar_n"), 4109),
        (("geometry", "ordinary_reference_n"), 1941),
        (("geometry", "calendar_n"), 4110.0),
        (("advisory_resource_observation_only",), False),
        (("advisory_resource_observation_only",), 1),
        (("current_performance_proven",), True),
        (("current_performance_proven",), 0),
        (("reuses_numerical_payload",), True),
        (("reuses_numerical_payload",), 0),
        (("historical_profile", "bytes"), 1),
        (("historical_profile", "sha256"), "0" * 64),
        (("historical_profile", "path"), "relative/resource-profile.json"),
        (("historical_source", "source_id"), "changed-historical-source"),
        (("historical_source", "runtime"), {"python": "changed"}),
        (("historical_source", "platform"), "changed-platform"),
        (("historical_source", "numerical_thread_limits"), {"OMP_NUM_THREADS": "2"}),
        (("selected", "workers"), 4),
        (("selected", "workers"), 1),
        (("selected", "workers"), 2.0),
        (("selected", "memory_cap_bytes"), 8 * 1024**3),
    ],
)
def test_wrapper_drift_is_rejected(packet: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
    target = packet["wrapper"]
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    _rewrite(packet, "wrapper")
    with pytest.raises(ValueError):
        _load(packet)


@pytest.mark.parametrize(("calendar_n", "ordinary_n"), [(4109, 1942), (4110, 1941), (4110.0, 1942), (True, 1942)])
def test_argument_geometry_must_match_registered_observation(packet: dict[str, Any], calendar_n: Any, ordinary_n: Any) -> None:
    with pytest.raises(ValueError, match="geometry"):
        _load(packet, calendar_n=calendar_n, ordinary_reference_n=ordinary_n)


@pytest.mark.parametrize("field", ["source", "input_id", "schema"])
def test_historical_preparation_identity_drift_is_rejected(packet: dict[str, Any], field: str) -> None:
    packet["preparation"][field] = "changed"
    _rewrite(packet, "preparation")
    with pytest.raises(ValueError, match="preparation"):
        _load(packet)


def test_historical_source_must_be_complete(packet: dict[str, Any]) -> None:
    packet["wrapper"]["historical_source"] = {"source_id": packet["historical_source"]["source_id"]}
    _rewrite(packet, "wrapper")
    with pytest.raises(ValueError, match="complete source"):
        _load(packet)


def test_changed_historical_payload_rejected_before_validator(packet: dict[str, Any]) -> None:
    with packet["path"].open("ab") as stream:
        stream.write(b" ")  # Still legal JSON, but physically differs.
    with pytest.raises(ValueError, match="bytes/hash"):
        _load(packet)
    packet["validator"].assert_not_called()


def test_historical_profile_input_is_checked_against_preparation(packet: dict[str, Any]) -> None:
    packet["historical"]["input_id"] = "changed-historical-input"
    packet["path"].write_bytes(canonical(packet["historical"]))
    packet["wrapper"]["historical_profile"].update(bytes=packet["path"].stat().st_size, sha256=file_digest(packet["path"]))
    _rewrite(packet, "wrapper")
    with pytest.raises(ValueError, match="preparation"):
        _load(packet)
    packet["validator"].assert_called_once_with(packet["historical"], source=packet["historical_source"], input_id="changed-historical-input")

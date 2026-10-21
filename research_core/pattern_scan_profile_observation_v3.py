"""Explicit advisory reuse of historical resource observations, never payloads."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from research_core.artifact_store import describe_file, object_digest, read_json, safe_path
from research_core.live_producer import read_stable
from research_core.pattern_scan_profile_v1 import validate_profile

LOGGER = logging.getLogger(__name__)
SCHEMA = "pattern-scan-profile-observation.v3"
GEOMETRY = {"calendar_n": 4110, "ordinary_reference_n": 1942}
OBSERVATION_FLAGS = {
    "advisory_resource_observation_only": True,
    "current_performance_proven": False,
    "reuses_numerical_payload": False,
}


def load_execution_profile(
    path: Path,
    *,
    source: dict[str, Any],
    input_id: str,
    calendar_n: int,
    ordinary_reference_n: int,
) -> dict[str, Any]:
    """Validate a current profile or an explicit historical advisory wrapper.

    Historical source/input identities remain intact. Selected limits must be
    byte-canonically identical to the historical profile, whose usual validator
    still enforces the registered hard limits. This establishes neither current
    performance nor numerical compatibility of a changed/dirty code checkout.
    """
    path = safe_path(path)
    record = read_json(path)
    if record.get("schema") == "pattern-scan-resource-profile.v1":
        validate_profile(record, source=source, input_id=input_id)
        return record
    try:
        return _observation(record, source, input_id, calendar_n, ordinary_reference_n)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"malformed profile observation: {error}") from error


def _observation(
    record: dict[str, Any],
    source: dict[str, Any],
    input_id: str,
    calendar_n: int,
    ordinary_reference_n: int,
) -> dict[str, Any]:
    if record.get("schema") != SCHEMA:
        raise ValueError("unsupported execution profile schema")
    if record.get("current_source_id") != source["source_id"] or record.get("current_input_id") != input_id:
        raise ValueError("profile observation current source/input differs")
    geometry = {"calendar_n": calendar_n, "ordinary_reference_n": ordinary_reference_n}
    if any(type(value) is not int for value in geometry.values()) or geometry != GEOMETRY or object_digest(record["geometry"]) != object_digest(geometry):
        raise ValueError("profile observation geometry differs")
    if any(record.get(name) is not value for name, value in OBSERVATION_FLAGS.items()):
        raise ValueError("profile observation requires explicit advisory-only boolean flags")
    descriptor = record["historical_profile"]
    if not isinstance(descriptor, dict) or set(descriptor) != {"path", "bytes", "sha256"}:
        raise ValueError("historical profile requires an exact file descriptor")
    if not isinstance(descriptor["path"], str) or not Path(descriptor["path"]).is_absolute():
        raise ValueError("historical profile requires a physical absolute path")
    historical_path = safe_path(Path(descriptor["path"]))

    def read_profile(location: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        return describe_file(location.parent, location), read_json(location)

    observed, historical = read_stable(historical_path, read_profile)
    if type(descriptor["bytes"]) is not int or descriptor["bytes"] != observed["bytes"] or descriptor["sha256"] != observed["sha256"]:
        raise ValueError("historical profile descriptor bytes/hash differs")
    historical_source = record["historical_source"]
    required = {"schema", "source_id", "runtime", "platform", "numerical_thread_limits"}
    if not isinstance(historical_source, dict) or not required.issubset(historical_source):
        raise ValueError("historical profile requires its complete source identity")
    for name in ("runtime", "platform", "numerical_thread_limits"):
        if object_digest(historical_source[name]) != object_digest(source[name]):
            raise ValueError(f"historical/current source {name} differs")
    historical_input = historical["input_id"]
    validate_profile(historical, source=historical_source, input_id=historical_input)
    preparation = read_json(safe_path(historical_path.parent / "derived-preparation.json"), max_bytes=128_000_000)
    if (
        preparation.get("schema") != "pattern-scan-derived-preparation.v2"
        or object_digest(preparation.get("source")) != object_digest(historical_source)
        or preparation.get("input_id") != historical_input
    ):
        raise ValueError("historical profile preparation source/input differs")
    if object_digest(record["selected"]) != object_digest(historical["selected"]):
        raise ValueError("profile observation selected limits differ from historical observations")
    LOGGER.info(
        "Loaded advisory resource observation historical_source=%s historical_input=%s current_source=%s current_input=%s",
        historical_source["source_id"],
        historical_input,
        source["source_id"],
        input_id,
    )
    return {
        **historical,
        "observation_provenance": {
            "schema": SCHEMA,
            "historical_source": historical_source,
            "historical_source_id": historical_source["source_id"],
            "historical_input_id": historical_input,
            "historical_profile": {**descriptor, "path": str(historical_path)},
            "current_source_id": source["source_id"],
            "current_input_id": input_id,
            "geometry": geometry,
            **OBSERVATION_FLAGS,
        },
    }

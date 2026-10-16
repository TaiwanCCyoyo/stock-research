"""Disk admission for one deferred-publication preparation or stock phase."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from research_core.artifact_store import file_digest, read_json
from research_core.research_data_paths import _checked_path

LOGGER = logging.getLogger(__name__)
SCHEMA = "pattern-scan-phase-capacity.v3"
POLICY = "results-only-deferred.v3"
MIN_RESERVE_BYTES = 32 * 1024**3
PHASE_COMPONENTS = {
    "prepare": ("prepared_prices", "phase_metadata", "retained_staging"),
    "stock": ("stock_checkpoints", "phase_metadata", "retained_staging"),
}


def assess_phase_capacity(
    plan: dict[str, Any],
    *,
    phase: str,
    source_id: str,
    input_id: str,
    profile_path: Path,
    available_bytes: int,
) -> dict[str, Any]:
    """Validate one phase's identities and additional bytes, never the full study.

    Already existing shared bytes belong in the evidence text, not the estimate
    of additional allocation. Unknown estimates are rejected, including metadata
    and staging; explicit zero estimates still require evidence.
    """
    if not isinstance(phase, str) or phase not in PHASE_COMPONENTS:
        raise ValueError("only prepare or stock phase capacity can be admitted")
    if any(not isinstance(value, str) or not value.strip() for value in (source_id, input_id)):
        raise ValueError("explicit nonempty source_id and input_id required")
    required_keys = {"schema", "phase", "publication_policy", "source_id", "input_id", "profile", "geometry", "components", "reserve_bytes"}
    if not isinstance(plan, dict) or set(plan) != required_keys or plan.get("schema") != SCHEMA:
        raise ValueError("explicit single-phase capacity plan required")
    if plan["phase"] != phase or plan["publication_policy"] != POLICY or plan["source_id"] != source_id or plan["input_id"] != input_id:
        raise ValueError("phase capacity source/input/phase/publication policy differs")
    geometry = plan["geometry"]
    if (
        not isinstance(geometry, dict)
        or set(geometry) != {"calendar_n", "ordinary_reference_n"}
        or type(geometry["calendar_n"]) is not int
        or geometry["calendar_n"] != 4110
        or type(geometry["ordinary_reference_n"]) is not int
        or geometry["ordinary_reference_n"] != 1942
    ):
        raise ValueError("phase capacity requires the fixed full-market geometry")
    if type(available_bytes) is not int or available_bytes < 0:
        raise ValueError("measured nonnegative available bytes required")
    reserve = plan["reserve_bytes"]
    if type(reserve) is not int or reserve < MIN_RESERVE_BYTES:
        raise ValueError("phase disk reserve must be at least 32 GiB")
    components = plan["components"]
    if not isinstance(components, dict) or set(components) != set(PHASE_COMPONENTS[phase]):
        raise ValueError("exact phase-specific disk components required")
    measured = 0
    for name, record in components.items():
        if (
            not isinstance(record, dict)
            or set(record) != {"estimated_bytes", "evidence"}
            or type(record.get("estimated_bytes")) is not int
            or record["estimated_bytes"] < 0
            or not isinstance(record.get("evidence"), str)
            or not record["evidence"].strip()
        ):
            raise ValueError(f"explicit nonnegative estimate and evidence required: {name}")
        measured += record["estimated_bytes"]
    profile = plan["profile"]
    if (
        not isinstance(profile, dict)
        or set(profile) != {"path", "bytes", "sha256"}
        or not isinstance(profile.get("path"), str)
        or not Path(profile["path"]).is_absolute()
        or type(profile.get("bytes")) is not int
        or profile["bytes"] < 0
        or not isinstance(profile.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", profile["sha256"]) is None
        or not isinstance(profile_path, Path)
        or not profile_path.is_absolute()
    ):
        raise ValueError("explicit physical absolute profile path and byte/hash pin required")
    supplied = _checked_path(profile_path)
    pinned = _checked_path(Path(profile["path"]))
    if supplied != pinned or not supplied.is_file() or supplied.stat().st_size != profile["bytes"] or file_digest(supplied) != profile["sha256"]:
        raise ValueError("phase capacity profile path/bytes/hash differs")
    required = measured + reserve
    result = {
        "phase": phase,
        "phase_only": True,
        "full_study_admitted": False,
        "publication_policy": POLICY,
        "source_id": source_id,
        "input_id": input_id,
        "available_bytes": available_bytes,
        "known_estimate_bytes": measured,
        "reserve_bytes": reserve,
        "required_bytes": required,
        "sufficient": available_bytes >= required,
    }
    LOGGER.info("Assessed phase-only capacity phase=%s required=%d available=%d sufficient=%s", phase, required, available_bytes, result["sufficient"])
    return result


def require_phase_capacity(
    plan_path: Path,
    primary: Path,
    *,
    phase: str,
    source_id: str,
    input_id: str,
    profile_path: Path,
) -> dict[str, Any]:
    """Require the explicit phase plan against current free disk space."""
    if not isinstance(plan_path, Path) or not plan_path.is_absolute() or not _checked_path(plan_path).is_file():
        raise ValueError("explicit existing absolute phase capacity plan required")
    if not isinstance(primary, Path) or not primary.is_absolute() or not _checked_path(primary).is_dir():
        raise ValueError("explicit existing primary directory required")
    result = assess_phase_capacity(
        read_json(plan_path),
        phase=phase,
        source_id=source_id,
        input_id=input_id,
        profile_path=profile_path,
        available_bytes=shutil.disk_usage(primary).free,
    )
    if not result["sufficient"]:
        raise ValueError(f"phase capacity is not established: {result}")
    return result

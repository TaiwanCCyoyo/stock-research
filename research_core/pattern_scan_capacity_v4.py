"""Admission for additional allocation of exactly one PR17 continuation phase."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from research_core.artifact_store import describe_file, read_json
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import host_resources

LOGGER = logging.getLogger(__name__)
SCHEMA = "pattern-scan-continuation-capacity.v4"
MIN_RESERVE_BYTES = 32 * 1024**3
MIN_HOST_RESERVE_BYTES = 4 * 1024**3
MAX_JOB_BYTES = 8 * 1024**3
PHASE_COMPONENTS = {
    "prices": ("comparison_metadata",),
    "barrier": ("global_tables", "phase_metadata"),
    "events": ("event_parts", "phase_metadata"),
    "analysis": ("event_parts", "summary_tables", "q4_draws", "followup_observations", "phase_metadata"),
}
SHA256 = re.compile(r"[0-9a-f]{64}")


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"explicit integer >= {minimum} required: {label}")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"nonblank text required: {label}")
    return value


def assess_continuation_capacity(
    plan: dict[str, Any],
    *,
    phase: str,
    executor: dict[str, Any],
    source_id: str,
    input_id: str,
    available_disk_bytes: int,
    available_memory_bytes: int,
) -> dict[str, Any]:
    """Pure validation of supplied incremental estimates and observed headroom.

    Components mean new allocation only: existing prices, stock checkpoints and
    shared-family bytes are excluded. Estimates and their evidence are supplied
    by the caller; this function never invents an estimate or measures a payload.
    Evidence descriptors are shape-checked here, physically verified by require.
    """
    if not isinstance(phase, str) or phase not in PHASE_COMPONENTS:
        raise ValueError("only prices, barrier, events or analysis continuation phase can be admitted")
    if not isinstance(executor, dict):
        raise ValueError("actual executor source identity required")
    executor_id = _text(executor.get("source_id"), "executor.source_id")
    _text(source_id, "ancestral source_id")
    _text(input_id, "original input_id")
    keys = {"schema", "phase", "executor_source_id", "ancestral_source_id", "input_id", "geometry", "components", "memory", "reserve_bytes", "evidence"}
    if not isinstance(plan, dict) or set(plan) != keys or plan.get("schema") != SCHEMA:
        raise ValueError("exact single-phase continuation capacity schema required")
    if plan["phase"] != phase or plan["executor_source_id"] != executor_id or plan["ancestral_source_id"] != source_id or plan["input_id"] != input_id:
        raise ValueError("continuation phase/executor/ancestral source/input differs")
    geometry = plan["geometry"]
    if (
        not isinstance(geometry, dict)
        or set(geometry) != {"calendar_n", "ordinary_reference_n"}
        or type(geometry["calendar_n"]) is not int
        or geometry["calendar_n"] != 4110
        or type(geometry["ordinary_reference_n"]) is not int
        or geometry["ordinary_reference_n"] != 1942
    ):
        raise ValueError("continuation capacity requires the fixed 4110/1942 geometry")
    available_disk_bytes = _integer(available_disk_bytes, "available disk")
    available_memory_bytes = _integer(available_memory_bytes, "available host memory")
    reserve = _integer(plan["reserve_bytes"], "disk reserve", minimum=MIN_RESERVE_BYTES)
    components = plan["components"]
    if not isinstance(components, dict) or set(components) != set(PHASE_COMPONENTS[phase]):
        raise ValueError("exact phase-specific additional-allocation components required")
    additional = 0
    for name, component in components.items():
        if not isinstance(component, dict) or set(component) != {"estimated_bytes", "evidence"}:
            raise ValueError(f"explicit additional estimate/evidence required: {name}")
        additional += _integer(component["estimated_bytes"], name)
        _text(component["evidence"], name + " evidence")
    memory = plan["memory"]
    if not isinstance(memory, dict) or set(memory) != {"estimated_peak_bytes", "job_limit_bytes", "host_reserve_bytes", "evidence"}:
        raise ValueError("explicit peak/job/host reserve memory estimate and evidence required")
    peak = _integer(memory["estimated_peak_bytes"], "estimated memory peak", minimum=1)
    job = _integer(memory["job_limit_bytes"], "job limit", minimum=1)
    host_reserve = _integer(memory["host_reserve_bytes"], "host reserve", minimum=MIN_HOST_RESERVE_BYTES)
    _text(memory["evidence"], "memory evidence")
    if not peak < job <= MAX_JOB_BYTES:
        raise ValueError("estimated memory peak must be below a job limit of at most eight GiB")
    evidence = plan["evidence"]
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("nonempty pinned continuation evidence list required")
    for descriptor in evidence:
        if not isinstance(descriptor, dict) or set(descriptor) != {"path", "bytes", "sha256", "role"}:
            raise ValueError("exact continuation evidence descriptor required")
        path = _text(descriptor["path"], "evidence path")
        if not Path(path).is_absolute() or ".." in Path(path).parts or "\0" in path:
            raise ValueError("explicit absolute evidence path without traversal required")
        _integer(descriptor["bytes"], "evidence bytes")
        _text(descriptor["role"], "evidence role")
        if not isinstance(descriptor["sha256"], str) or SHA256.fullmatch(descriptor["sha256"]) is None:
            raise ValueError("canonical evidence SHA-256 required")
    required_disk, required_memory = additional + reserve, job + host_reserve
    result = {
        "phase": phase,
        "phase_only": True,
        "full_study_admitted": False,
        "executor_source_id": executor_id,
        "ancestral_source_id": source_id,
        "input_id": input_id,
        "disk": {
            "additional_estimate_bytes": additional,
            "reserve_bytes": reserve,
            "required_bytes": required_disk,
            "available_bytes": available_disk_bytes,
            "sufficient": available_disk_bytes >= required_disk,
        },
        "memory": {
            "estimated_peak_bytes": peak,
            "job_limit_bytes": job,
            "host_reserve_bytes": host_reserve,
            "required_bytes": required_memory,
            "available_bytes": available_memory_bytes,
            "sufficient": available_memory_bytes >= required_memory,
        },
        "sufficient": available_disk_bytes >= required_disk and available_memory_bytes >= required_memory,
    }
    LOGGER.info(
        "Assessed continuation phase=%s disk=%d/%d memory=%d/%d sufficient=%s",
        phase,
        required_disk,
        available_disk_bytes,
        required_memory,
        available_memory_bytes,
        result["sufficient"],
    )
    return result


def require_continuation_capacity(
    path: Path,
    *,
    run: Path,
    phase: str,
    executor: dict[str, Any],
    source_id: str,
    input_id: str,
) -> dict[str, Any]:
    """Verify pins and admit only this phase against current disk/host memory."""
    if not isinstance(path, Path) or not path.is_absolute() or not checked_path(path).is_file():
        raise ValueError("explicit existing absolute continuation capacity plan required")
    if not isinstance(run, Path) or not run.is_absolute() or not checked_path(run).is_dir():
        raise ValueError("explicit existing absolute continuation run directory required")
    plan = read_json(checked_path(path))
    result = assess_continuation_capacity(
        plan,
        phase=phase,
        executor=executor,
        source_id=source_id,
        input_id=input_id,
        available_disk_bytes=shutil.disk_usage(run).free,
        available_memory_bytes=host_resources()["physical_available_bytes"],
    )
    if not result["sufficient"]:
        raise ValueError(f"continuation capacity not established; pending_phase={phase}: {result}")
    verified: dict[Path, tuple[int, str]] = {}
    for descriptor in plan["evidence"]:
        evidence_path = checked_path(Path(descriptor["path"]))
        pin = (descriptor["bytes"], descriptor["sha256"])
        if evidence_path in verified:
            if verified[evidence_path] != pin:
                raise ValueError("conflicting continuation evidence pins for one physical path")
            continue
        if not evidence_path.is_file():
            raise ValueError(f"continuation evidence missing: {evidence_path}")
        actual = describe_file(evidence_path.parent, evidence_path)
        if actual["bytes"] != pin[0] or actual["sha256"] != pin[1]:
            raise ValueError(f"continuation evidence bytes/hash differs: {evidence_path}")
        verified[evidence_path] = pin
    return result

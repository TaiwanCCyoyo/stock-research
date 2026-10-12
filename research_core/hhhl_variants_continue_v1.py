"""Resume the fixed study from a verified complete daily cache, without new rules.

Attempt 1 and its sealed implementation remain unchanged. The operator stops its
own writer before sealing the cache; this module never terminates processes.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from research_core.artifact_store import describe_file, file_digest, object_digest, read_json, safe_path, verify_files, write_json
from research_core.hhhl_variants_inputs import FrozenInputs
from research_core.hhhl_variants_run import ROOT, TASK, implementation_receipt

LOG = logging.getLogger(__name__)
OWNER = "01a12bfc-b535-7352-bef7-68fe3a56901e"


def cache_seal(primary: Path, source: Path, pins: Path, writer_stopped: dict[str, Any]) -> dict[str, Any]:
    """Record verified complete daily shards after an operator-confirmed stop.

    The stop assertion records the exact PID, owner and prior code commit. It is
    evidence supplied by the operator, not a process-liveness claim by Python.
    """
    source = safe_path(source)
    parent = safe_path(primary / TASK / "datasets")
    if source.parent != parent or not source.name.startswith(".staging-hhhl-v4-variants-01-"):
        raise ValueError("cache must be this task's primary staging directory")
    execution = read_json(source / "execution-start.json")
    if writer_stopped.get("owner") != OWNER or writer_stopped.get("code_commit") != execution["code_commit"]:
        raise ValueError("stopped writer identity differs from the original attempt")
    pid = writer_stopped.get("pid")
    if writer_stopped.get("verified_stopped") is not True or isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("operator must verify the exact prior writer has stopped")
    if (source / "selection.json").exists() or (source / "summary.parquet").exists():
        raise ValueError("this continuation requires an attempt without aggregate results or selected candidates")
    inputs = FrozenInputs(primary, pins)
    daily = safe_path(source / "daily")
    expected = {f"{ordinal:04}.parquet" for ordinal in range(1, len(inputs.tables) + 1)}
    if {path.name for path in daily.iterdir()} != expected:
        raise ValueError("daily cache inventory is incomplete or contains extra entries")
    artifacts = []
    for ordinal, table in enumerate(inputs.tables, 1):
        path = daily / f"{ordinal:04}.parquet"
        descriptor = describe_file(source, path)
        descriptor["rows"] = pq.ParquetFile(path).metadata.num_rows
        descriptor["code"] = table["security_id"].split(":", 1)[1]
        if descriptor["rows"] != inputs.pins["calendar"]["rows"]:
            raise ValueError("daily cache length differs from the pinned calendar")
        artifacts.append(descriptor)
    inputs.verify_after()
    seal = {
        "schema_version": "hhhl-variants-daily-cache-seal.v1",
        "source": str(source),
        "original_execution": execution,
        "original_execution_sha256": file_digest(source / "execution-start.json"),
        "input_pins_sha256": file_digest(pins),
        "writer_stopped": writer_stopped,
        "artifacts": artifacts,
        "retained_attempt_artifacts": [describe_file(source, path) for path in sorted(source.rglob("*")) if path.is_file()],
        "reason": (
            "Performance interruption; identical approved definitions and selection. No completed aggregate or selection artifact exists for attempt 1."
        ),
    }
    write_json(source / "daily-cache-seal.json", seal)
    return seal


def verified_cache(source: Path, seal_path: Path, pins: Path, inputs: FrozenInputs) -> dict[str, Any]:
    """Fail closed on any cache lineage, inventory, identity or byte change."""
    source, seal_path = safe_path(source), safe_path(seal_path)
    if seal_path != source / "daily-cache-seal.json":
        raise ValueError("cache seal must belong to the retained attempt")
    seal = read_json(seal_path)
    if seal.get("schema_version") != "hhhl-variants-daily-cache-seal.v1" or seal.get("source") != str(source):
        raise ValueError("cache seal schema or source differs")
    if seal.get("input_pins_sha256") != file_digest(pins):
        raise ValueError("cache input pins differ")
    if seal.get("original_execution_sha256") != file_digest(source / "execution-start.json"):
        raise ValueError("original execution receipt changed")
    artifacts = seal["artifacts"]
    expected = {f"daily/{ordinal:04}.parquet" for ordinal in range(1, len(inputs.tables) + 1)}
    if len(artifacts) != len(expected) or {item["path"] for item in artifacts} != expected:
        raise ValueError("cache descriptor inventory differs")
    verify_files(source, artifacts)
    for ordinal, table in enumerate(inputs.tables, 1):
        descriptor = next(item for item in artifacts if item["path"] == f"daily/{ordinal:04}.parquet")
        if descriptor["code"] != table["security_id"].split(":", 1)[1] or descriptor["rows"] != inputs.pins["calendar"]["rows"]:
            raise ValueError("cache code or calendar differs")
    for name, digest in seal["original_execution"]["code_sha256"].items():
        if file_digest(ROOT / name) != digest:
            raise ValueError("original sealed implementation changed")
    return seal


def execute_cached(primary: Path, pins: Path, publication: Path, approved_merge: str, source: Path) -> dict[str, Any]:
    """Execute one unchanged specification with a sealed cache and new receipt."""
    from research_core.hhhl_variants_continue_pipeline_v1 import run_cached_study
    from research_core.hhhl_variants_publication_v1 import publish_result

    execution = implementation_receipt(approved_merge)
    cli = ROOT / "scripts/continue_hhhl_variants.py"
    execution["code_sha256"][cli.relative_to(ROOT).as_posix()] = file_digest(cli)
    final = safe_path(primary / TASK / "datasets/hhhl-v4-variants-01")
    publication = safe_path(publication)
    if final.exists() or publication.exists():
        raise FileExistsError("fixed dataset/publication already exists")
    lock = safe_path(final.parent / f".{final.name}.lock")
    write_json(lock, {"pid": os.getpid(), "owner": OWNER, "execution": execution})
    inputs = FrozenInputs(primary, pins)
    source = safe_path(source)
    seal_path = source / "daily-cache-seal.json"
    seal = verified_cache(source, seal_path, pins, inputs)
    execution["cache_lineage"] = {
        "path": str(seal_path),
        "sha256": file_digest(seal_path),
        "cache_identity": object_digest(seal),
        "original_code_commit": seal["original_execution"]["code_commit"],
        "original_started_at_utc": seal["original_execution"]["started_at_utc"],
        "same_approved_specification": True,
    }
    staging = safe_path(final.parent / f".staging-{final.name}-{uuid.uuid4().hex}")
    staging.mkdir()
    write_json(staging / "execution-start.json", execution)
    write_json(staging / "cache-lineage.json", execution["cache_lineage"])
    summary, selection = run_cached_study(inputs, staging, source, seal["artifacts"])
    inputs.verify_after()
    verified_cache(source, seal_path, pins, inputs)
    if any(file_digest(ROOT / name) != digest for name, digest in execution["code_sha256"].items()):
        raise ValueError("implementation changed during continuation")
    receipt = publish_result(inputs, pins, staging, final, publication, summary, selection, execution, ROOT / TASK / "mission.md")
    lock.unlink()
    LOG.info("Fixed continuation published dataset=%s summary_rows=%d", receipt["dataset_id"], len(summary))
    return receipt

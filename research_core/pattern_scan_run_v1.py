"""Task-owned fresh-source dispatch over the approved fixed research snapshot."""

from __future__ import annotations

import logging
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from research_core.artifact_store import file_digest, object_digest, publish_noreplace, read_json, relative_name, write_json
from research_core.pattern_scan_barrier_v1 import build_barrier, publish_stock_versions, verified_parts, verify_barrier
from research_core.pattern_scan_execution_v1 import (
    BOOTSTRAP,
    ROOT,
    _MemoryBoundJob,
    _verify_loaded,
    run_requests,
    source_identity,
    verify_source,
    write_source_archive,
)
from research_core.pattern_scan_inputs_v1 import load_snapshot
from research_core.pattern_scan_pipeline_v1 import prepare_requests, profile_requests, representative_codes
from research_core.pattern_scan_preflight_v1 import profile_global
from research_core.pattern_scan_profile_v1 import validate_profile
from research_core.research_data_catalog import verify_entry
from research_core.research_data_paths import DataRoots, _artifact_name, _checked_path
from research_core.research_measurement_v1 import host_resources, phase_receipt, resource_sample

LOGGER = logging.getLogger(__name__)


def verify_completion(saved: dict[str, Any], request: dict[str, Any], roots: DataRoots) -> None:
    """A cached receipt certifies current bytes only after their revalidation."""
    source = request["source"]
    verify_source(source)
    if saved.get("request_id") != object_digest(request) or saved.get("complete") is not True:
        raise ValueError("invalid existing coordinator completion")
    snapshot = load_snapshot(roots, manifest_sha256=request["input_manifest_sha256"])
    snapshot.verify_after()
    input_id = snapshot.input_id
    del snapshot
    result = saved["result"]
    if result["phase"] == "resource_profile":
        profile = read_json(_checked_path(Path(result["profile_path"])))
        if profile != result["profile"] or profile["source_id"] != source["source_id"] or profile["input_id"] != input_id:
            raise ValueError("completed profile identity differs")
        validate_profile(profile, source=source, input_id=input_id)
    else:
        verified_parts(result["pool"]["results"], source=source, input_id=input_id)
        verify_barrier(result["barrier"])
        for entry in result["shared_versions"].values():
            verify_entry(entry, roots)
        if result["phase"] == "complete_pattern_scan":
            for key in ("shared_event_outcomes", "shared_episodes", "shared_report_tables"):
                verify_entry(result["analysis"][key], roots)
    verify_source(source)


def launch(
    roots: DataRoots,
    *,
    mode: str,
    input_manifest_sha256: str,
    run_id: str,
    calculation_authorized: bool = False,
    profile_path: Path | None = None,
    memory_bytes: int = 6 * 1024**3,
    job_memory_bytes: int = 8 * 1024**3,
    timeout_seconds: float = 8 * 3600,
) -> dict[str, Any]:
    """Launch one owned bounded coordinator; never use a stale imported runner."""
    if calculation_authorized is not True:
        raise PermissionError("explicit approved fixed-input calculation authorization required")
    if mode not in {"profile", "stock", "all"} or not run_id or relative_name(run_id) != run_id or "/" in run_id:
        raise ValueError("explicit phase and one task run identifier required")
    if type(memory_bytes) is not int or type(job_memory_bytes) is not int or not 0 < memory_bytes < job_memory_bytes <= 8 * 1024**3:
        raise ValueError("finite coordinator and child memory caps required")
    available = host_resources()["physical_available_bytes"]
    if available is None or available - job_memory_bytes < 4 * 1024**3:
        raise ValueError("cannot establish coordinator cap and four GiB host reserve")
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds < 86400:
        raise ValueError("bounded coordinator timeout required")
    _artifact_name(run_id)
    roots.validate_worktree(ROOT)
    run = _checked_path(roots.primary / ".tmp" / "pattern-scan-execution" / run_id)
    run.mkdir(parents=True, exist_ok=True)
    source = source_identity(("scripts/pattern_scan.py", "research_core/pattern_scan_run_v1.py", "research_core/pattern_scan_stock_v1.py"))
    seal = run / "seal"
    source_path = seal / "source.json"
    if seal.exists():
        if read_json(source_path) != source:
            raise ValueError("run source identity changed; new sealed run required")
        retained = read_json(seal / "source-archive.json")
        if retained.get("source_id") != source["source_id"] or file_digest(seal / "executed-sources.zip") != retained["sha256"]:
            raise ValueError("retained raw source archive changed")
    else:
        staging = run / f".seal-{uuid.uuid4().hex}"
        staging.mkdir()
        digest = write_source_archive(staging / "executed-sources.zip", source)
        write_json(staging / "source.json", source)
        write_json(staging / "source-archive.json", {"source_id": source["source_id"], "sha256": digest})
        verify_source(source)
        publish_noreplace(staging, seal)
    profile = None if profile_path is None else read_json(_checked_path(profile_path))
    if mode != "profile":
        if profile is None:
            raise ValueError("formal calculation requires same-source measured representative profile")
        validate_profile(profile, source=source)
    request = {
        "schema": "pattern-scan-coordinator-request.v1",
        "mode": mode,
        "calculation_authorized": True,
        "primary": str(roots.primary),
        "data": str(roots.data),
        "run_root": str(run),
        "input_manifest_sha256": input_manifest_sha256,
        "source": source,
        "profile": profile,
        "memory_bytes": memory_bytes,
        "source_git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }
    path = run / f"request-{object_digest(request)}.json"
    response = path.with_suffix(".response.json")
    if path.exists():
        if read_json(path) != request:
            raise ValueError("coordinator request differs")
    else:
        write_json(path, request)
    if response.exists():
        saved = read_json(response, max_bytes=128_000_000)
        verify_completion(saved, request, roots)
        return saved
    job = _MemoryBoundJob(job_memory_bytes)
    started = time.monotonic()
    try:
        process = job.start([sys.executable, "-c", BOOTSTRAP, str(ROOT), str(path)], ROOT)
        while process.poll() is None:
            if time.monotonic() - started > timeout_seconds:
                raise TimeoutError("owned research coordinator exceeded fixed timeout")
            time.sleep(0.2)
        if process.returncode != 0:
            raise ValueError(f"owned research coordinator failed exit={process.returncode}; retained scratch={run}")
        saved = read_json(response, max_bytes=128_000_000)
        if saved.get("request_id") != object_digest(request) or saved.get("complete") is not True:
            raise ValueError("coordinator response differs or incomplete")
        verify_source(source)
        saved["coordinator_job_memory"] = job.memory_receipt()
        return saved
    finally:
        job.terminate_and_confirm()
        job.close()


def coordinator_main(request_path: Path) -> None:
    """Fresh compiled entry; receipts identify phases rather than imply Q results."""
    from research_core.cache_execution import require_loaded

    require_loaded({"run": Path(__file__), "execution": ROOT / "research_core/pattern_scan_execution_v1.py"})
    request = read_json(_checked_path(request_path))
    if request.get("calculation_authorized") is not True or request.get("schema") != "pattern-scan-coordinator-request.v1":
        raise PermissionError("approved coordinator protocol required")
    source = request["source"]
    verify_source(source)
    roots = DataRoots(Path(request["primary"]), Path(request["data"]))
    run = _checked_path(Path(request["run_root"]))
    if run.parent != roots.primary / ".tmp" / "pattern-scan-execution" or request_path.parent != run:
        raise ValueError("coordinator outside explicit primary task scratch")
    before = resource_sample()
    snapshot = load_snapshot(roots, manifest_sha256=request["input_manifest_sha256"])
    loaded = resource_sample()
    mode = request["mode"]
    if mode == "profile":
        profile_path = run / "resource-profile.json"
        if profile_path.exists():
            profile = read_json(profile_path, max_bytes=64_000_000)
            validate_profile(profile, source=source, input_id=snapshot.input_id)
        else:
            profile = _profile(snapshot, source, run, request["memory_bytes"], before, loaded)
            validate_profile(profile, source=source, input_id=snapshot.input_id)
            write_json(profile_path, profile)
        snapshot.verify_after()
        result: dict[str, Any] = {"phase": "resource_profile", "profile_path": str(profile_path), "profile": profile}
    elif mode in {"stock", "all"}:
        profile = request["profile"]
        validate_profile(profile, source=source, input_id=snapshot.input_id)
        codes = tuple(sorted(snapshot.inventory.loc[snapshot.inventory["included"], "code"].astype(str)))
        packets, preparation = prepare_requests(snapshot, codes, source, run, calculation_authorized=True)
        benchmark = snapshot.stock("0050")
        snapshot.verify_after()
        input_id = snapshot.input_id
        del snapshot
        limits = profile["selected"]
        pool = run_requests(
            packets,
            workers=limits["workers"],
            memory_bytes=limits["memory_cap_bytes"],
            estimated_worker_bytes=limits["estimated_worker_bytes"],
            stocks_per_process=limits["stocks_per_process"],
            timeout_seconds=limits["timeout_seconds"],
        )
        # Re-open and verify the canonical raw bytes before any formal publication.
        checked = load_snapshot(roots, manifest_sha256=request["input_manifest_sha256"])
        checked.verify_after()
        del checked
        parts = verified_parts(pool["results"], source=source, input_id=input_id)
        barrier = build_barrier(parts, benchmark, run / "global")
        entries = publish_stock_versions(roots, parts, barrier, source=source, input_id=input_id)
        result = {"phase": "full_stock_shared_versions", "pool": pool, "price_preparation": preparation, "barrier": barrier, "shared_versions": entries}
        if mode == "all":
            from research_core.pattern_scan_analysis_v1 import run_analysis

            result["analysis"] = run_analysis(roots, parts, barrier, entries, run / "analysis", source=source, input_id=input_id)
            result["phase"] = "complete_pattern_scan"
    else:
        raise ValueError("unsupported fixed calculation phase")
    verify_source(source)
    final_snapshot = load_snapshot(roots, manifest_sha256=request["input_manifest_sha256"])
    final_snapshot.verify_after()
    del final_snapshot
    _verify_loaded(source)
    write_json(
        request_path.with_suffix(".response.json"),
        {
            "schema": "pattern-scan-coordinator-receipt.v1",
            "complete": True,
            "request_id": object_digest(request),
            "source_id": source["source_id"],
            "input_manifest_sha256": request["input_manifest_sha256"],
            "source_git_commit": request["source_git_commit"],
            "result": result,
            "measurements": [phase_receipt("coordinator_total", before, resource_sample())],
        },
    )
    LOGGER.info("Completed approved scan phase=%s run=%s", result["phase"], run)


def _profile(snapshot: Any, source: dict[str, Any], run: Path, memory_bytes: int, before: dict[str, Any], loaded: dict[str, Any]) -> dict[str, Any]:
    codes, strata = representative_codes(snapshot)
    packets, preparation = prepare_requests(snapshot, codes, source, run, calculation_authorized=True)
    profile = profile_requests(packets, memory_bytes=memory_bytes, estimated_worker_bytes=512 * 1024**2, stocks_per_process=1)
    profile["strata"] = strata
    profile["snapshot_loading"] = phase_receipt("fixed_snapshot_loading", before, loaded)
    profile["price_preparation"] = preparation
    reference = verified_parts(profile["profiles"][0]["results"], source=source, input_id=snapshot.input_id)
    representative = {code: reference[code] for code in sorted(reference)[:4]}
    profile["global_preflight"] = profile_global(
        representative, snapshot.stock("0050"), run / f"preflight-{uuid.uuid4().hex}", source=source, input_id=snapshot.input_id
    )
    profile["estimate"] = {
        "ordinary_reference_n": int(snapshot.inventory["included"].sum()),
        "calendar_n": len(snapshot.calendar),
        "stock_independent_worker_seconds": sum(
            phase["wall_seconds"] for result in profile["profiles"][0]["results"] for phase in result["measurements"] if phase["phase"] == "stock_calculation"
        )
        / len(codes)
        * int(snapshot.inventory["included"].sum()),
        "remaining_global_and_report_seconds": None,
        "remaining_estimate_reason": "Representative phase observations are retained; full target/event counts are not yet measured",
        "global_stock_calendar_row_n": int(snapshot.inventory["included"].sum()) * len(snapshot.calendar),
        "binding_target_stock_n": 12 * int(snapshot.inventory["included"].sum()),
        "main_single_full_row_cap": 5_529_600,
        "candidate_confirmation_full_row_cap": 211_968,
        "full_drop_annual_rows_per_cell_cap": 19,
        "followup_landmark_cell_cap": 6_842_880,
    }
    snapshot.verify_after()
    return profile

"""Bounded continuation from completed stock work and pinned shared prices.

The old stock source is numerical ancestry, not the executing checkout. Each new
phase records its actual executor separately. Stock kernels are never rerun.
"""

from __future__ import annotations

import logging
import math
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from research_core.artifact_store import describe_file, file_digest, object_digest
from research_core.pattern_scan_capacity_v4 import require_continuation_capacity
from research_core.pattern_scan_execution_v1 import ROOT, _MemoryBoundJob
from research_core.pattern_scan_git_source_v2 import assert_current_code, git_source_identity
from research_core.pattern_scan_inputs_v1 import read_preparation_pins
from research_core.pattern_scan_price_references_v4 import EQUALITY, HANDOFF, RETIRED, create_price_handoff, read_benchmark, retire_own_prices
from research_core.pattern_scan_receipt_io_v2 import read_scan_receipt
from research_core.pattern_scan_result_lifecycle_v3 import ACTIVE, _retain, _run
from research_core.pattern_scan_shared_prices_v4 import make_price_reference
from research_core.research_data_paths import DataRoots, _artifact_name, _checked_path
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
SCHEMA = "pattern-scan-continuation.v4"
PHASES = ("prices", "retire-prices", "barrier", "analysis")
BOOTSTRAP = """
import logging,os,sys
from pathlib import Path
sys.dont_write_bytecode=True
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ[name]='1'
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
root=Path(sys.argv[1]);sys.path.insert(0,str(root))
from research_core.pattern_scan_continuation_v4 import coordinator_main
coordinator_main(Path(sys.argv[2]))
"""


def _save(directory: Path, name: str, body: dict[str, Any]) -> None:
    scratch = directory.parent / f".continuation-metadata-{uuid.uuid4().hex}"
    try:
        _retain(directory / name, body, scratch=scratch)
    finally:
        if scratch.is_dir() and not any(scratch.iterdir()):
            scratch.rmdir()


def _descriptor(path: Path) -> dict[str, Any]:
    return {**describe_file(path.parent, path), "path": str(path)}


def _verify_output(response: Path, request: dict[str, Any]) -> dict[str, Any]:
    saved = read_scan_receipt(response)
    if saved.get("schema") != SCHEMA or saved.get("complete") is not True or saved.get("request_id") != object_digest(request):
        raise ValueError("continuation result identity differs")
    if any(saved.get(key) != request[key] for key in ("phase", "source", "executor", "input_id")):
        raise ValueError("continuation result source or phase differs")
    for record in saved["results"].values():
        path = _checked_path(Path(record["path"]))
        if path.stat().st_size != record["bytes"] or file_digest(path) != record["sha256"]:
            raise ValueError("retained continuation result changed")
    memory_path = response.with_suffix(".job-memory.json")
    memory = read_scan_receipt(memory_path)
    if memory.get("request_id") != object_digest(request) or memory.get("response_sha256") != file_digest(response) or memory.get("complete") is not True:
        raise ValueError("continuation native Job evidence differs")
    observation = memory["job_memory"]
    if (
        type(observation.get("limit_bytes")) is not int
        or not 0 < observation["limit_bytes"] <= 8 * 1024**3
        or type(observation.get("peak_committed_bytes")) is not int
        or not 0 < observation["peak_committed_bytes"] <= observation["limit_bytes"]
        or observation.get("scope") != "virtual memory committed across this owned Windows job"
    ):
        raise ValueError("continuation native Job memory limit/peak evidence invalid")
    return {**saved, "coordinator_job_memory": memory["job_memory"]}


def launch(
    roots: DataRoots,
    *,
    run_id: str,
    control_id: str,
    phase: str,
    capacity_path: Path,
    generation: str | None = None,
    calculation_authorized: bool = False,
    retirement_authorized: bool = False,
    timeout_seconds: float = 8 * 3600,
) -> dict[str, Any]:
    """Run exactly one admitted phase under the existing finite native Job."""
    if calculation_authorized is not True:
        raise PermissionError("explicit approved continuation required")
    if phase not in PHASES or type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 8 * 3600:
        raise ValueError("one explicit finite continuation phase required")
    if phase == "retire-prices" and retirement_authorized is not True:
        raise PermissionError("explicit own-price retirement authorization required")
    for name in (run_id, control_id):
        if _artifact_name(name) != name or "/" in name:
            raise ValueError("one primary task-owned run/control identifier required")
    roots.validate_worktree(ROOT)
    run = _run(roots.primary / ".tmp/pattern-scan-execution" / run_id)
    control = _checked_path(run.parent / control_id)
    if control == run:
        raise ValueError("continuation control metadata must be outside the completed stock run")
    control.mkdir(exist_ok=True)
    capacity_path = _checked_path(capacity_path)
    request_path = control / f"request-{phase}.json"
    response = control / f"response-{phase}.json"
    prepared = read_scan_receipt(run / "derived-preparation.json")
    if request_path.exists():
        request = read_scan_receipt(request_path)
        if (
            request.get("schema") != SCHEMA
            or request.get("calculation_authorized") is not True
            or request.get("phase") != phase
            or request.get("run_root") != str(run)
            or request.get("control_root") != str(control)
            or request.get("primary") != str(roots.primary)
            or request.get("data") != str(roots.data)
            or request.get("source") != prepared["source"]
            or request.get("input_id") != prepared["input_id"]
            or request.get("timeout_seconds") != timeout_seconds
            or request.get("capacity_path") != str(capacity_path)
            or request.get("retirement_authorized") != retirement_authorized
            or (generation is not None and request.get("reference", {}).get("generation") != generation)
        ):
            raise ValueError("continuation retry parameters differ")
        if response.exists() and response.with_suffix(".job-memory.json").exists():
            return _verify_output(response, request)
    else:
        executor = git_source_identity(ROOT)
        if phase == "prices":
            if generation is None:
                raise ValueError("explicit shared generation required, no latest fallback")
            pins = read_preparation_pins(ROOT / "tasks/20261013-pattern-scan/params/input-pins-v1.json.gz")
            calendar = pd.DatetimeIndex(pd.to_datetime(pins["price_observation"]["calendar"]["dates"]))
            reference = make_price_reference(shared_data_root(), generation, calendar, expected_fingerprint=prepared["producer_fingerprint"])
            handoff = None
        else:
            body = read_scan_receipt(run / HANDOFF)
            reference = body["reference"]
            handoff = _descriptor(run / HANDOFF)
        request = {
            "schema": SCHEMA,
            "phase": phase,
            "calculation_authorized": True,
            "retirement_authorized": retirement_authorized,
            "run_root": str(run),
            "control_root": str(control),
            "primary": str(roots.primary),
            "data": str(roots.data),
            "source": prepared["source"],
            "input_id": prepared["input_id"],
            "executor": executor,
            "stock_reference": _descriptor(run / "phase-stock-result.json"),
            "reference": reference,
            "price_handoff": handoff,
            "capacity_path": str(capacity_path),
            "capacity_sha256": file_digest(capacity_path),
            "timeout_seconds": timeout_seconds,
            "active_owner": uuid.uuid4().hex,
        }
        _save(control, request_path.name, request)
    if (run / ACTIVE).exists():
        raise ValueError("active scan marker blocks a second owned continuation Job")
    if response.exists():
        raise ValueError("completed response without native Job receipt requires evidence recovery, not a new computation")
    assert_current_code(request["executor"], ROOT)
    if file_digest(capacity_path) != request["capacity_sha256"]:
        raise ValueError("continuation capacity plan changed")
    assessment = require_continuation_capacity(
        capacity_path,
        run=run,
        phase="prices" if phase == "retire-prices" else phase,
        executor=request["executor"],
        source_id=request["source"]["source_id"],
        input_id=request["input_id"],
    )
    job_limit = assessment["memory"]["job_limit_bytes"]
    token = {"request_id": object_digest(request), "owner": request["active_owner"]}
    _save(run, ACTIVE, token)
    job = None
    started = time.monotonic()
    try:
        LOGGER.info("Starting owned continuation phase=%s executor=%s ancestral_source=%s", phase, request["executor"]["code"], request["source"]["source_id"])
        job = _MemoryBoundJob(job_limit)
        process = job.start([sys.executable, "-c", BOOTSTRAP, str(ROOT), str(request_path)], ROOT)
        while process.poll() is None:
            if time.monotonic() - started > timeout_seconds:
                raise TimeoutError("owned continuation timeout; original checkpoints and completed phase outputs retained")
            time.sleep(0.2)
        if process.returncode != 0:
            raise ValueError(f"owned continuation failed exit={process.returncode}; metadata retained at {control}")
        _save(
            control,
            response.with_suffix(".job-memory.json").name,
            {
                "schema": "pattern-scan-continuation-job-memory.v4",
                "complete": True,
                "request_id": object_digest(request),
                "response_sha256": file_digest(response),
                "job_memory": job.memory_receipt(),
            },
        )
        return _verify_output(response, request)
    finally:
        if job is not None:
            job.terminate_and_confirm()
            job.close()
        if (run / ACTIVE).exists() and read_scan_receipt(run / ACTIVE) == token:
            (run / ACTIVE).unlink()


def coordinator_main(path: Path) -> None:
    request = read_scan_receipt(_checked_path(path))
    if request.get("schema") != SCHEMA or request.get("calculation_authorized") is not True:
        raise PermissionError("approved continuation protocol required")
    executor = request["executor"]
    assert_current_code(executor, ROOT)
    run, control = _run(Path(request["run_root"])), _run(Path(request["control_root"]))
    if path.parent != control or run.parent != control.parent:
        raise ValueError("continuation request outside primary owned control directory")
    phase = request["phase"]
    if phase not in PHASES or path.name != f"request-{phase}.json" or run == control:
        raise ValueError("explicit distinct run/control and named phase request required")
    if (control / f"response-{phase}.json").exists():
        raise ValueError("coordinator response already exists; use parent evidence verification")
    if read_scan_receipt(run / ACTIVE) != {"request_id": object_digest(request), "owner": request["active_owner"]}:
        raise ValueError("continuation does not own the active native Job marker")
    if file_digest(Path(request["capacity_path"])) != request["capacity_sha256"]:
        raise ValueError("continuation capacity identity changed")
    require_continuation_capacity(
        Path(request["capacity_path"]),
        run=run,
        phase="prices" if phase == "retire-prices" else phase,
        executor=executor,
        source_id=request["source"]["source_id"],
        input_id=request["input_id"],
    )
    if phase == "prices":
        result = create_price_handoff(run, request["reference"], executor=executor, calculation_authorized=True, active_owner=request["active_owner"])
        outputs = {"price_handoff": run / HANDOFF, "equivalence": run / EQUALITY}
    elif phase == "retire-prices":
        descriptor = request["price_handoff"]
        if file_digest(Path(descriptor["path"])) != descriptor["sha256"]:
            raise ValueError("continuation price handoff changed")
        result = retire_own_prices(
            run,
            {key: descriptor[key] for key in ("path", "sha256")},
            retirement_authorized=request["retirement_authorized"],
            active_owner=request["active_owner"],
        )
        outputs = {"price_retirement": run / RETIRED}
    else:
        from research_core.pattern_scan_barrier_v1 import build_barrier, checkpoint_label_entry, verified_parts, verify_barrier

        stock = read_scan_receipt(Path(request["stock_reference"]["path"]))
        stock_path = _checked_path(Path(request["stock_reference"]["path"]))
        if (
            stock_path != run / "phase-stock-result.json"
            or stock_path.stat().st_size != request["stock_reference"]["bytes"]
            or file_digest(stock_path) != request["stock_reference"]["sha256"]
        ):
            raise ValueError("original completed stock reference changed")
        handoff = request["price_handoff"]
        if _descriptor(run / HANDOFF) != handoff:
            raise ValueError("continuation shared-price handoff changed")
        parts = verified_parts(stock["pool"]["results"], source=request["source"], input_id=request["input_id"])
        if phase == "barrier":
            result = build_barrier(parts, read_benchmark(run), run / "global")
            outputs = {"barrier": run / "global/receipt.json"}
        elif phase == "analysis":
            from research_core.pattern_scan_analysis_v1 import run_analysis

            barrier = read_scan_receipt(run / "global/receipt.json")
            verify_barrier(barrier)
            result = run_analysis(
                DataRoots(Path(request["primary"]), Path(request["data"])),
                parts,
                barrier,
                {"labels": checkpoint_label_entry(parts, source=request["source"], input_id=request["input_id"])},
                run / "analysis",
                source=request["source"],
                input_id=request["input_id"],
                defer_publication=True,
                continuation_request=path,
            )
            outputs = {"computed_results": Path(result["retained_result"]["path"])}
        else:
            raise ValueError("unsupported continuation phase")
    assert_current_code(executor, ROOT)
    _save(
        control,
        f"response-{phase}.json",
        {
            "schema": SCHEMA,
            "complete": True,
            "phase": phase,
            "request_id": object_digest(request),
            "source": request["source"],
            "executor": executor,
            "input_id": request["input_id"],
            "result": result,
            "results": {name: _descriptor(output) for name, output in outputs.items()},
        },
    )

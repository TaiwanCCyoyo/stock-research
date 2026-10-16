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

from research_core.artifact_store import describe_file, file_digest, object_digest, read_json
from research_core.pattern_scan_capacity_v4 import require_continuation_capacity
from research_core.pattern_scan_execution_v1 import ROOT, _MemoryBoundJob
from research_core.pattern_scan_git_source_v2 import assert_current_code, git_source_identity, verify_git_source
from research_core.pattern_scan_inputs_v1 import read_preparation_pins
from research_core.pattern_scan_price_references_v4 import EQUALITY, HANDOFF, RETIRED, create_price_handoff, read_benchmark, retire_own_prices
from research_core.pattern_scan_receipt_io_v2 import read_scan_receipt
from research_core.pattern_scan_result_lifecycle_v3 import ACTIVE, _retain, _run
from research_core.pattern_scan_shared_prices_v4 import make_price_reference
from research_core.research_data_paths import DataRoots, _artifact_name, _checked_path
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
SCHEMA = "pattern-scan-continuation.v4"
PHASES = ("prices", "retire-prices", "barrier", "events", "analysis")
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


def read_phase_history(request: dict[str, Any]) -> tuple[dict[str, dict[str, Path]], dict[str, Path]]:
    """Resolve pinned historical metadata without copying or relabeling phases."""
    descriptor = request.get("phase_history")
    if descriptor is None:
        return {}, {}
    if request.get("phase") not in {"events", "analysis"}:
        raise ValueError("historical phase metadata is only used by events or analysis")
    run, control = _checked_path(Path(request["run_root"])), _checked_path(Path(request["control_root"]))

    def pinned(record: dict[str, Any]) -> Path:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "bytes", "sha256"}
            or not isinstance(record["path"], str)
            or type(record["bytes"]) is not int
            or record["bytes"] < 0
        ):
            raise ValueError("phase history metadata descriptor invalid")
        path = _checked_path(Path(record["path"]))
        if not path.is_absolute() or path.suffix != ".json" or not path.is_relative_to(run.parent) or _descriptor(path) != record:
            raise ValueError("phase history metadata pin or location differs")
        return path

    def previous_control(value: str) -> Path:
        path = _checked_path(Path(value))
        if not path.is_absolute() or path.parent != run.parent or path in {run, control}:
            raise ValueError("phase history control must be a distinct original sibling")
        return path

    def previous_request(path: Path, parent: Path, phase: str) -> dict[str, Any]:
        previous = read_scan_receipt(path)
        if (
            path != parent / f"request-{phase}.json"
            or previous.get("schema") != SCHEMA
            or previous.get("phase") != phase
            or previous.get("control_root") != str(parent)
            or any(previous.get(key) != request[key] for key in ("run_root", "primary", "data", "source", "input_id", "stock_reference", "reference"))
            or previous.get("calculation_authorized") is not True
        ):
            raise ValueError("phase history request ancestry differs")
        verify_git_source(previous["executor"])
        return previous

    history_path = pinned(descriptor)
    history = read_json(history_path)
    if (
        set(history) != {"schema", "run_root", "source_id", "input_id", "phases", "interrupted"}
        or history.get("schema") != "pattern-scan-phase-history.v4"
        or history.get("run_root") != str(run)
        or history.get("source_id") != request["source"]["source_id"]
        or history.get("input_id") != request["input_id"]
        or not isinstance(history.get("phases"), dict)
        or not set(history["phases"]) <= {"prices", "retire-prices", "barrier", "events"}
        or not isinstance(history.get("interrupted"), list)
        or len(history["interrupted"]) > 8
    ):
        raise ValueError("phase history identity or scope differs")
    phases: dict[str, dict[str, Path]] = {}
    retained = {"execution/phase-history.json": history_path}
    for phase, record in history["phases"].items():
        if not isinstance(record, dict) or set(record) != {"control_root", "files"} or not isinstance(record.get("files"), dict):
            raise ValueError("phase history phase metadata invalid")
        parent = previous_control(record["control_root"])
        if set(record["files"]) != {"request", "response", "job-memory", "capacity"}:
            raise ValueError("phase history requires complete phase evidence")
        paths = {kind: pinned(value) for kind, value in record["files"].items()}
        previous = previous_request(paths["request"], parent, phase)
        if (
            paths["response"] != parent / f"response-{phase}.json"
            or paths["job-memory"] != parent / f"response-{phase}.job-memory.json"
            or paths["capacity"] != _checked_path(Path(previous["capacity_path"]))
            or _descriptor(paths["capacity"])["sha256"] != previous["capacity_sha256"]
        ):
            raise ValueError("phase history phase locators differ")
        # Incomplete/cancelled work cannot be adopted as a completed phase.
        verify_phase_result(paths["response"], previous)
        phases[phase] = paths
    for index, record in enumerate(history["interrupted"]):
        if not isinstance(record, dict) or set(record) != {"control_root", "phase", "request", "cancellation"} or record.get("phase") not in PHASES:
            raise ValueError("phase history interruption metadata invalid")
        parent = previous_control(record["control_root"])
        phase = record["phase"]
        path, cancellation_path = pinned(record["request"]), pinned(record["cancellation"])
        previous_request(path, parent, phase)
        cancellation = read_json(cancellation_path)
        if (
            cancellation.get("schema") != "pattern-scan-owner-directed-cancellation.v1"
            or cancellation.get("run_root") != str(run)
            or cancellation.get("control_root") != str(parent)
            or cancellation.get("request") != record["request"]
            or cancellation.get("complete_response") is not False
            or cancellation.get("checkpoints_preserved") is not True
            or (parent / f"response-{phase}.json").exists()
            or (parent / f"response-{phase}.job-memory.json").exists()
            or (phase in phases and phases[phase]["request"].parent == parent)
        ):
            raise ValueError("phase history interruption cannot certify completion")
        retained[f"execution/interruptions/{index}/request.json"] = path
        retained[f"execution/interruptions/{index}/cancellation.json"] = cancellation_path
    LOGGER.info("Verified historical continuation metadata completed_phases=%d interrupted_attempts=%d", len(phases), len(history["interrupted"]))
    return phases, retained


def verify_phase_result(response: Path, request: dict[str, Any]) -> dict[str, Any]:
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


def record_analysis_completion(request_path: Path) -> dict[str, Any]:
    """Retain bounded completion evidence after the parent has closed its Job.

    Historical executor identity is evidence, not a requirement on current code.
    The computed index and expanded response remain untouched and are pinned.
    This does not verify scientific delivery or authorize publication/cleanup.
    """
    if not request_path.is_absolute():
        raise ValueError("explicit absolute completed analysis request required")
    request_path = _checked_path(request_path)
    request = read_json(request_path)  # Small protocol evidence, default byte bound.
    run = _run(Path(request["run_root"]))
    control = _run(Path(request["control_root"]))
    if (
        request.get("schema") != SCHEMA
        or request.get("phase") != "analysis"
        or request.get("calculation_authorized") is not True
        or request_path != control / "request-analysis.json"
        or run == control
        or run.parent != control.parent
        or request.get("run_root") != str(run)
        or request.get("control_root") != str(control)
        or request.get("primary") != str(run.parent.parent.parent)
        or request.get("data") != str(run.parent.parent.parent / "research_data")
    ):
        raise ValueError("completed analysis request identity or locator differs")
    if (run / ACTIVE).exists():
        raise ValueError("active native Job blocks analysis completion evidence")
    verify_git_source(request["executor"])
    prepared = read_scan_receipt(run / "derived-preparation.json")
    handoff_path = _checked_path(run / HANDOFF)
    reference = read_scan_receipt(handoff_path)["reference"]
    stock_path = _checked_path(run / "phase-stock-result.json")
    if (
        request.get("source") != prepared.get("source")
        or request.get("input_id") != prepared.get("input_id")
        or request.get("price_handoff") != _descriptor(handoff_path)
        or request.get("reference") != reference
        or request.get("stock_reference") != _descriptor(stock_path)
    ):
        raise ValueError("completed analysis ancestry or shared reference differs")
    response_path = _checked_path(control / "response-analysis.json")
    job_path = _checked_path(response_path.with_suffix(".job-memory.json"))
    response = read_scan_receipt(response_path)
    computed_path = _checked_path(run / "computed-results.json")
    results = response.get("results")
    if (
        not isinstance(results, dict)
        or set(results) != {"computed_results"}
        or not isinstance(results["computed_results"], dict)
        or set(results["computed_results"]) != {"path", "bytes", "sha256"}
        or results["computed_results"]["path"] != str(computed_path)
    ):
        raise ValueError("completed analysis must pin this run's exact computed index")
    del response  # Release expanded phase metadata before the shared verifier reads it.
    job = read_json(job_path)  # Never copy expanded stock metadata into this audit.
    if job.get("schema") != "pattern-scan-continuation-job-memory.v4":
        raise ValueError("completed analysis native Job schema differs")
    verified = verify_phase_result(response_path, request)
    if verified["results"] != results:
        raise ValueError("completed analysis result locators changed during verification")
    response_identity = {key: verified[key] for key in ("schema", "complete", "phase", "request_id", "source", "executor", "input_id", "results")}
    native_job_memory = verified["coordinator_job_memory"]
    del verified
    computed = read_scan_receipt(computed_path)
    if (
        computed.get("schema") != "pattern-scan-computed-results.v3"
        or computed.get("complete") is not True
        or computed.get("state") != "computed_unpublished"
        or computed.get("run_root") != str(run)
        or computed.get("source") != request["source"]
        or computed.get("input_id") != request["input_id"]
        or computed.get("provenance", {}).get("executor") != request["executor"]
        or computed.get("provenance", {}).get("stock_reference") != request["stock_reference"]
        or computed.get("provenance", {}).get("shared_price_reference") != request["reference"]
    ):
        raise ValueError("completed computed index identity differs")
    # verify_phase_result already checked the full response hash against the Job.
    # Keep its byte identity plus only the small protocol projection, not result.
    body = {
        "schema": "pattern-scan-continuation-completion.v4",
        "complete": True,
        "phase": "analysis",
        "run_root": str(run),
        "source": request["source"],
        "executor": request["executor"],
        "input_id": request["input_id"],
        "shared_reference": request["reference"],
        "computed_results": results["computed_results"],
        "request": {"descriptor": _descriptor(request_path), "contents": request},
        "response": {
            "descriptor": {"path": str(response_path), "bytes": response_path.stat().st_size, "sha256": job["response_sha256"]},
            "identity": response_identity,
        },
        "job": {"descriptor": _descriptor(job_path), "contents": job},
        "native_job_memory": native_job_memory,
    }
    audit_dir = _checked_path(run / "analysis/audits")
    audit_dir.mkdir(parents=True, exist_ok=True)
    _save(audit_dir, "continuation-completion.json", body)
    return _descriptor(audit_dir / "continuation-completion.json")


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
    history_path: Path | None = None,
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
    if history_path is not None and phase not in {"events", "analysis"}:
        raise ValueError("historical phase metadata is only used by events or analysis")
    history_pin = _descriptor(_checked_path(history_path)) if history_path is not None else None
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
            or request.get("phase_history") != history_pin
            or (generation is not None and request.get("reference", {}).get("generation") != generation)
        ):
            raise ValueError("continuation retry parameters differ")
        read_phase_history(request)
        if response.exists() and response.with_suffix(".job-memory.json").exists():
            return verify_phase_result(response, request)
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
        if history_pin is not None:
            request["phase_history"] = history_pin
        read_phase_history(request)
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
        return verify_phase_result(response, request)
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
    read_phase_history(request)
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
        elif phase == "events":
            from research_core.pattern_scan_analysis_v1 import prepare_event_parts
            from research_core.pattern_scan_conditions_v1 import PATTERNS

            barrier_path = run / "global/receipt.json"
            barrier = read_scan_receipt(barrier_path)
            verify_barrier(barrier)
            original_codes = [row["code"] for row in stock["pool"]["results"]]
            calendar = request["reference"]["calendar"]["dates"]
            if (
                len(parts) != 1942
                or len(original_codes) != 1942
                or len(set(original_codes)) != 1942
                or set(parts) != set(original_codes)
                or set(barrier["global_files"]) != set(parts)
                or barrier.get("source_id") != request["source"]["source_id"]
                or barrier.get("input_id") != request["input_id"]
                or len(calendar) != 4110
                or object_digest(barrier["calendar"]) != object_digest(calendar)
            ):
                raise ValueError("events continuation requires the original full-market 1942-stock/4110-session barrier")
            label_checkpoint = checkpoint_label_entry(parts, source=request["source"], input_id=request["input_id"])
            event_parts = prepare_event_parts(
                parts,
                barrier,
                {"labels": label_checkpoint},
                run / "analysis/event-parts",
                source=request["source"],
                input_id=request["input_id"],
            )
            if set(event_parts) != set(PATTERNS) or any(set(by_code) != set(parts) for by_code in event_parts.values()):
                raise ValueError("event checkpoint must cover every registered target and original stock")
            event_root = _checked_path(run / "analysis/event-parts")
            event_receipts: dict[str, dict[str, Any]] = {}
            for target, by_code in sorted(event_parts.items()):
                event_receipts[target] = {}
                for code, directory in sorted(by_code.items()):
                    directory = _checked_path(directory)
                    if not directory.is_relative_to(event_root) or directory == event_root:
                        raise ValueError("new event receipts must remain under this run's event checkpoint root")
                    event_receipts[target][code] = _descriptor(_checked_path(directory / "receipt.json"))
            checkpoint = {
                "schema": "pattern-scan-event-checkpoint.v4",
                "complete": True,
                "phase_only": True,
                "full_study_admitted": False,
                "source": request["source"],
                "input_id": request["input_id"],
                "executor": executor,
                "stock_reference": request["stock_reference"],
                "price_handoff": handoff,
                "barrier_receipt": _descriptor(barrier_path),
                "label_checkpoint": label_checkpoint,
                "event_parts": {
                    target: {code: str(directory) for code, directory in sorted(by_code.items())} for target, by_code in sorted(event_parts.items())
                },
                "event_receipts": event_receipts,
            }
            checkpoint_path = run / "event-checkpoint.json"
            _save(run, checkpoint_path.name, checkpoint)
            result = {
                "phase": "event_parts_checkpoint",
                "phase_only": True,
                "full_study_admitted": False,
                "target_n": len(event_parts),
                "stock_n": len(parts),
                "event_checkpoint_path": str(checkpoint_path),
            }
            outputs = {"event_checkpoint": checkpoint_path}
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

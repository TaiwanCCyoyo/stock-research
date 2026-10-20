"""Local Q2--Q6 coordination; only final result files receive hashes."""

from __future__ import annotations

import logging
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from research_core.artifact_store import publish_noreplace, read_json, write_json
from research_core.hhhl_variants_selection import Atom
from research_core.pattern_scan_conditions_v1 import PATTERNS
from research_core.pattern_scan_local_conditions_v5 import run_conditions
from research_core.pattern_scan_local_followup_v5 import run_followup
from research_core.pattern_scan_local_inputs_v5 import LocalInputs, write_progress
from research_core.pattern_scan_local_q4_v5 import run_q4
from research_core.research_data_paths import checked_path
from research_core.research_measurement_v1 import phase_receipt, resource_sample
from research_core.run_receipt import InputSpec, code_identity, fingerprint_inputs, write_run_receipt

LOGGER = logging.getLogger(__name__)
PHASES = ("conditions", "q4", "followup")
DEFINITION = "pattern-scan-local-remaining.v5"


def _remove_owned_temporary(path: Path, output: Path) -> None:
    """Retire this run's new scratch only after its final results are recorded."""
    if not path.exists():
        return
    path, output = checked_path(path), checked_path(output)
    if not path.is_relative_to(output) or path == output or "_temporary" not in path.parts:
        raise ValueError("scratch cleanup must remain inside this continuation's temporary area")
    for child in path.rglob("*"):
        checked_path(child)
    shutil.rmtree(path)


def run_remaining(stock_result: Path, output: Path, *, repo_root: Path, targets: tuple[str, ...], phases: tuple[str, ...] = PHASES) -> dict[str, Any]:
    """Continue selected original families without restarting stock/global/Q1.

    One target is active at a time. Conditions retain group-level progress;
    followup retains stock-level progress. Their disposable projections are
    removed after all three final components for that target have receipts.
    Neither the original run, Q1, preview nor a shared generation is deleted.
    Release is deliberately left to the caller after full Q2--Q6 completion.
    """
    repo_root, output = checked_path(repo_root), checked_path(output)
    if not output.is_relative_to(repo_root / ".tmp") or output == repo_root / ".tmp":
        raise ValueError("remaining research output must be under the calling worktree's .tmp")
    if not targets or len(set(targets)) != len(targets) or not set(targets).issubset(PATTERNS):
        raise ValueError("unique original target families required")
    if not phases or len(set(phases)) != len(phases) or not set(phases).issubset(PHASES):
        raise ValueError("registered continuation phases required")
    executor = code_identity(repo_root)
    if executor["dirty"]:
        raise ValueError("research requires a clean committed executor")
    output.mkdir(parents=True, exist_ok=True)
    inputs = LocalInputs(stock_result, output / "_temporary")
    progress_path = output / "progress.json"
    scope = {"schema": DEFINITION, "stock_result": str(inputs.stock_result), "source_id": inputs.source_id, "input_id": inputs.input_id}
    progress = read_json(progress_path) if progress_path.exists() else {**scope, "completed": {}, "complete": False}
    if any(progress.get(key) != value for key, value in scope.items()):
        raise ValueError("continuation progress belongs to different original inputs")
    fingerprint = fingerprint_inputs([
        InputSpec("original_stock_result", inputs.stock_result, live_producer=False),
        InputSpec("original_preparation", inputs.run / "derived-preparation.json", live_producer=False),
        InputSpec("original_barrier", inputs.run / "global/receipt.json", live_producer=False),
    ])
    for target in targets:
        completed = progress["completed"].setdefault(target, {})
        for phase in phases:
            if phase in completed:
                receipt = read_json(Path(completed[phase]["receipt"]))
                if any(not Path(row["path"]).is_file() for row in receipt["results"].values()):
                    raise ValueError("completed final result is missing; repair the affected phase explicitly")
                LOGGER.info("Reuse complete target=%s phase=%s executor=%s", target, phase, receipt["code"]["commit"])
                continue
            if phase != "conditions" and "conditions" not in completed:
                raise ValueError("Q4--Q6 require completed fixed development/confirmation selection")
            final = output / target / phase
            working = output / target / f".staging-{phase}"
            working.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                receipt_path = final / "run-receipt.json"
                if not receipt_path.is_file():
                    raise ValueError("published local result lacks its final receipt")
                receipt = read_json(receipt_path)
                completed[phase] = {"receipt": str(receipt_path), "executor": receipt["code"], "recovered": True}
                write_progress(progress_path, progress)
                continue
            started = resource_sample()
            LOGGER.info("Start target=%s phase=%s original_stocks=%d", target, phase, len(inputs.codes))
            candidates = {}
            if phase != "conditions":
                selected = read_json(output / target / "conditions" / "top-candidates.json")
                candidates = {name: tuple(Atom(**atom) for atom in atoms) for name, atoms in selected.items()}
            if phase == "conditions":
                _, candidates, files = run_conditions(inputs, target, working)
                top_path = working / "top-candidates.json"
                if not top_path.exists():
                    write_json(top_path, {name: [asdict(atom) for atom in atoms] for name, atoms in candidates.items()})
                files.append(top_path)
            else:
                inputs.cache_target(target, inputs.temporary / "events" / target)
                if phase == "q4":
                    files = run_q4(inputs, target, candidates, working)
                else:
                    files = run_followup(inputs, target, candidates, working)
            # Schema/footer validation is a readability check of final output,
            # not another data hash or a new intermediate verification chain.
            for path in files:
                if path.suffix == ".parquet":
                    pq.ParquetFile(path).metadata
            measurement = phase_receipt(phase, started, resource_sample())
            receipt_path = working / "run-receipt.json"
            if not receipt_path.exists():
                write_run_receipt(
                    receipt_path,
                    run_id=f"{output.name}-{target}-{phase}",
                    definition=DEFINITION,
                    parameters={
                        "target": target,
                        "phase": phase,
                        "original_source_id": inputs.source_id,
                        "original_input_id": inputs.input_id,
                        "original_code": inputs.original_code,
                        "cutoff": "2026-10-12",
                        "horizons": [126, 252],
                        "measurement": measurement,
                        "Q1": "reuse existing pr17-q1-local-20261016; no Q1 computation",
                    },
                    inputs=fingerprint,
                    results={path.relative_to(working).as_posix(): path for path in files},
                    preregistration=repo_root / "tasks/20261013-pattern-scan/mission.md",
                    repo_root=repo_root,
                    shared_data=[inputs.shared_record],
                    expected_code=executor,
                )
            # Paths in the receipt must describe the final single-copy location.
            # No result bytes are copied or rehashed during this relocation.
            receipt = read_json(receipt_path)
            for row in receipt["results"].values():
                result_path = Path(row["path"])
                absolute = result_path if result_path.is_absolute() else repo_root / result_path
                row["path"] = str(final / absolute.relative_to(working))
            write_progress(receipt_path, receipt)
            final.parent.mkdir(parents=True, exist_ok=True)
            publish_noreplace(working, final)
            completed[phase] = {"receipt": str(final / "run-receipt.json"), "executor": executor}
            write_progress(progress_path, progress)
            LOGGER.info("Complete target=%s phase=%s final_files=%d", target, phase, len(files))
        if set(completed) == set(PHASES):
            _remove_owned_temporary(inputs.temporary / "events" / target, output)
            _remove_owned_temporary(output / target / "followup" / "_temporary", output)
    progress["complete"] = set(progress["completed"]) == set(PATTERNS) and all(set(value) == set(PHASES) for value in progress["completed"].values())
    progress["release_pending"] = progress["complete"]
    write_progress(progress_path, progress)
    return progress


def launch_remaining(arguments: list[str], repo_root: Path, output: Path, *, timeout_seconds: int) -> None:
    """Use the existing owned Windows Job with one explicit memory/time limit."""
    import subprocess
    import sys

    from research_core.pattern_scan_execution_v1 import _MemoryBoundJob
    from research_core.research_measurement_v1 import host_resources

    host = host_resources()
    available = host.get("physical_available_bytes")
    if available is None or available < 12 * 1024**3:
        raise ValueError("8 GiB job requires 4 GiB additional host reserve")
    repo_root, output = checked_path(repo_root), checked_path(output)
    if not output.is_relative_to(repo_root / ".tmp") or output == repo_root / ".tmp":
        raise ValueError("launch output must be below the calling worktree's .tmp")
    output.mkdir(parents=True, exist_ok=True)
    active = output / ".active"
    with active.open("x", encoding="utf-8") as stream:
        stream.write(str(__import__("os").getpid()))
    job = _MemoryBoundJob(8 * 1024**3)
    started = time.monotonic()
    try:
        process = job.start([sys.executable, "-m", "scripts.run_pattern_scan_remaining", *arguments, "--worker"], repo_root)
        while process.poll() is None:
            if time.monotonic() - started > timeout_seconds:
                job.terminate_and_confirm()
                raise TimeoutError("owned continuation exceeded its explicit timeout")
            time.sleep(0.5)
        write_progress(output / "job-memory.json", {**job.memory_receipt(), "wall_seconds": time.monotonic() - started, "exit_code": process.returncode})
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, process.args)
    finally:
        job.close()
        active.unlink(missing_ok=True)

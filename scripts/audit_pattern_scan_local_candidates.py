"""Audit fixed PR17 candidates from original derivatives, without event files."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    from research_core.pattern_scan_execution_v1 import _MemoryBoundJob
    from research_core.pattern_scan_local_candidate_audit_v5 import GROUPS, run_candidate_audit
    from research_core.pattern_scan_local_inputs_v5 import LocalInputs, write_progress
    from research_core.research_data_paths import checked_path
    from research_core.research_measurement_v1 import host_resources

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-result", type=Path, required=True)
    parser.add_argument("--conditions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group", choices=GROUPS, action="append")
    parser.add_argument("--horizon", type=int, choices=(126, 252), action="append")
    parser.add_argument("--max-frame-mib", type=int, default=512)
    parser.add_argument("--timeout-seconds", type=int, default=21600)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.max_frame_mib <= 0 or args.timeout_seconds <= 0:
        parser.error("memory and time limits must be positive")
    root = Path(__file__).resolve().parents[1]
    output = checked_path(args.output)
    if not output.is_relative_to(root / ".tmp") or output == root / ".tmp":
        parser.error("audit output must be in this checkout's .tmp")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Existing kernels remain unchanged; the adapter logs bounded stock progress.
    for module in ("pattern_scan_event_tables_v1", "pattern_scan_event_conditions_v1", "pattern_scan_events_v1"):
        logging.getLogger(f"research_core.{module}").setLevel(logging.WARNING)
    if args.worker:
        inputs = LocalInputs(args.stock_result, output / "_input_scope")
        result = run_candidate_audit(
            inputs,
            args.conditions,
            output,
            repo_root=root,
            groups=tuple(args.group) if args.group else None,
            horizons=tuple(args.horizon or (126, 252)),
            max_frame_bytes=args.max_frame_mib * 1024**2,
            max_seconds=args.timeout_seconds,
        )
        logging.info(
            "Candidate audit requested cases=%d checks=%d full_scope_complete=%s",
            result["completed_case_n"],
            result["aggregate_checks"],
            result["audit_complete"],
        )
        return
    available = host_resources().get("physical_available_bytes")
    if available is None or available < 16 * 1024**3:
        raise ValueError("4 GiB audit Job requires 12 GiB additional host reserve alongside the original executor")
    output.mkdir(parents=True, exist_ok=True)
    job = _MemoryBoundJob(4 * 1024**3)
    started = time.monotonic()
    try:
        process = job.start([sys.executable, "-m", "scripts.audit_pattern_scan_local_candidates", *sys.argv[1:], "--worker"], root)
        while process.poll() is None:
            if time.monotonic() - started > args.timeout_seconds:
                raise TimeoutError("owned candidate audit exceeded its time limit")
            time.sleep(0.5)
        write_progress(output / "job-memory.json", {**job.memory_receipt(), "wall_seconds": time.monotonic() - started, "exit_code": process.returncode})
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, process.args)
    finally:
        try:
            job.terminate_and_confirm()
        finally:
            job.close()


if __name__ == "__main__":
    main()

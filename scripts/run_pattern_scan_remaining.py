"""Continue original PR17 Q2--Q6 locally; leave Q1 and shared data unchanged."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from contextlib import nullcontext
from pathlib import Path

# Only new invocations read this default. An existing worker keeps its tuple.
DEFAULT_TARGET_ORDER = ("B1", "H1", "B2", "B4", "B3", "L1", "P1", "R1", "R2", "R3", "L2", "L3")


def main() -> None:
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    from research_core import scratch_runs
    from research_core.pattern_scan_conditions_v1 import PATTERNS
    from research_core.pattern_scan_local_remaining_v5 import PHASES, launch_remaining, output_run, run_remaining

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", choices=PATTERNS, action="append")
    parser.add_argument("--phase", choices=PHASES, action="append")
    parser.add_argument("--timeout-seconds", type=int, default=864000, help="owned worker limit (default: ten days, allowing the six-day continuation)")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("timeout must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = Path(__file__).resolve().parents[1]
    if args.worker:
        # The launcher owns the scratch writer lock for this worker's lifetime.
        # The worker emits progress.json; only that owner writes run.json.
        run_remaining(args.stock_result, args.output, repo_root=root, targets=tuple(args.target or DEFAULT_TARGET_ORDER), phases=tuple(args.phase or PHASES))
    else:
        record = output_run(args.output, root)
        context = scratch_runs.open_run(record["task"], record["run"], repo_root=root) if record is not None else nullcontext(None)
        with context as run:
            if run is not None:
                if run.record["state"] != "running":
                    parser.error("continuation needs a running scratch run")
                run.heartbeat(progress={"step": 0, "total": 1, "label": "Preparing continuation"})
            progress = launch_remaining(
                sys.argv[1:],
                root,
                args.output,
                timeout_seconds=args.timeout_seconds,
                on_progress=(lambda value: run.heartbeat(progress=value)) if run is not None else None,
            )
            if run is not None and progress.get("complete") is True:
                run.mark("complete")


if __name__ == "__main__":
    main()

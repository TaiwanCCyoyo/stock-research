"""Run a bounded PR17 local parallelism probe inside an open scratch run."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path


def main() -> int:
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    from research_core import scratch_runs
    from research_core.pattern_scan_local_parallel_probe_v5 import DEFAULT_WORKERS, run_probe

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-result", type=Path, required=True, help="absolute original stock-result receipt")
    parser.add_argument("--continuation", type=Path, required=True, help="paused q2-q6-v6 scratch run")
    parser.add_argument("--output", type=Path, required=True, help="already-open registered scratch run")
    parser.add_argument("--workers", type=int, nargs="+", default=list(DEFAULT_WORKERS))
    args = parser.parse_args()
    record = scratch_runs.read_run(args.output)
    if record["state"] != "running":
        parser.error("--output must name an already-open running scratch run")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    result = run_probe(args.stock_result, args.continuation, args.output, workers=tuple(args.workers))
    logging.getLogger(__name__).info("Probe completed output=%s", result["path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

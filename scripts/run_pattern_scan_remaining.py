"""Continue original PR17 Q2--Q6 locally; leave Q1 and shared data unchanged."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def main() -> None:
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    from research_core.pattern_scan_conditions_v1 import PATTERNS
    from research_core.pattern_scan_local_remaining_v5 import PHASES, launch_remaining, run_remaining

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", choices=PATTERNS, action="append")
    parser.add_argument("--phase", choices=PHASES, action="append")
    parser.add_argument("--timeout-seconds", type=int, default=172800)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        parser.error("timeout must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = Path(__file__).resolve().parents[1]
    if args.worker:
        run_remaining(args.stock_result, args.output, repo_root=root, targets=tuple(args.target or PATTERNS), phases=tuple(args.phase or PHASES))
    else:
        launch_remaining(sys.argv[1:], root, args.output, timeout_seconds=args.timeout_seconds)


if __name__ == "__main__":
    main()

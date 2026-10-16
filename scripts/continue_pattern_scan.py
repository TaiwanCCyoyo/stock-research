"""Continue one approved PR17 phase from completed stocks and shared prices."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from pathlib import Path

from research_core.pattern_scan_continuation_v4 import PHASES, launch
from research_core.research_data_paths import DataRoots
from research_core.shared_data import ENV_KEY


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=PHASES)
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--shared-root", type=Path, help=f"Override {ENV_KEY} for this process; otherwise use existing shared-root configuration")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--control-id", required=True)
    parser.add_argument("--capacity-plan", type=Path, required=True)
    parser.add_argument("--generation")
    parser.add_argument("--timeout-seconds", type=float, default=8 * 3600)
    parser.add_argument("--calculation-authorized", action="store_true")
    parser.add_argument("--retirement-authorized", action="store_true")
    args = parser.parse_args()
    if not args.calculation_authorized:
        parser.error("--calculation-authorized is required")
    if args.phase == "retire-prices" and not args.retirement_authorized:
        parser.error("retire-prices requires --retirement-authorized")
    if args.phase == "prices" and args.generation is None:
        parser.error("prices requires an explicit --generation")
    if not math.isfinite(args.timeout_seconds) or not 0 < args.timeout_seconds <= 8 * 3600:
        parser.error("--timeout-seconds must be finite, positive and at most eight hours")
    if args.shared_root is not None:
        if not args.shared_root.is_absolute():
            parser.error("--shared-root must be an explicit absolute external path")
        os.environ[ENV_KEY] = str(args.shared_root)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    receipt = launch(
        DataRoots(args.primary_root, args.data_root),
        run_id=args.run_id,
        control_id=args.control_id,
        phase=args.phase,
        capacity_path=args.capacity_plan,
        generation=args.generation,
        calculation_authorized=args.calculation_authorized,
        retirement_authorized=args.retirement_authorized,
        timeout_seconds=args.timeout_seconds,
    )
    sys.stdout.write(
        json.dumps({
            "complete": receipt["complete"],
            "phase": receipt["phase"],
            "source_id": receipt["source"]["source_id"],
            "executor_source_id": receipt["executor"]["source_id"],
        })
        + "\n"
    )


if __name__ == "__main__":
    main()

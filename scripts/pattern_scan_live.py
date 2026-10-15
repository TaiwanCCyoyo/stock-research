"""Run the approved pattern scan using fingerprinted live inputs and derived checkpoints."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from research_core.pattern_scan_run_v2 import launch
from research_core.producer_data import ENV_KEY
from research_core.research_data_paths import DataRoots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "profile", "storage-profile", "stock", "all"))
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--producer-root", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--capacity-plan", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=8 * 3600)
    parser.add_argument("--calculation-authorized", action="store_true")
    args = parser.parse_args()
    if args.producer_root is not None:
        os.environ[ENV_KEY] = str(args.producer_root)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    receipt = launch(
        DataRoots(args.primary_root, args.data_root),
        mode=args.mode,
        run_id=args.run_id,
        calculation_authorized=args.calculation_authorized,
        prepared_path=args.prepared,
        profile_path=args.profile,
        capacity_path=args.capacity_plan,
        timeout_seconds=args.timeout_seconds,
    )
    sys.stdout.write(json.dumps({"complete": receipt["complete"], "phase": receipt["result"]["phase"], "source_id": receipt["source_id"]}) + "\n")


if __name__ == "__main__":
    main()

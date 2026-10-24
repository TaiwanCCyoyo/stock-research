"""Build or inspect the maintained coverage family; HTTP never triggers this CLI."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from research_core.security_coverage_maintenance import measure_coverage, update_coverage
from research_core.security_coverage_store import CoverageStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect, profile, or maintain saved security coverage.")
    parser.add_argument("action", choices=("update", "status", "measure"))
    parser.add_argument("--seconds-per-source", type=float, default=180)
    parser.add_argument("--codes", nargs="+", help="selected stock codes for a bounded, non-publishing measure run")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.action == "status":
        if args.codes:
            parser.error("--codes is only valid with the measure action")
        result = CoverageStore().list(size=1)
        result.pop("rows", None)
    elif args.action == "measure":
        if not args.codes:
            parser.error("measure requires --codes CODE [CODE ...]")
        result = measure_coverage(args.codes, seconds_per_source=args.seconds_per_source)
    else:
        if args.codes:
            parser.error("--codes is only valid with the measure action")
        result = update_coverage(seconds_per_source=args.seconds_per_source)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

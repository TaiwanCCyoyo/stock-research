"""Publish a portable, partial PR17 Q1 web-report data directory."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from research_core.pattern_scan_report_v1 import export_q1_report_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--q1-root", type=Path, required=True, help="Existing directory containing all 12 Q1 family results")
    parser.add_argument("--output", type=Path, required=True, help="New report/data directory to create")
    parser.add_argument("--as-of", required=True, help="Report date in YYYY-MM-DD form")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    export_q1_report_data(args.q1_root, args.output, as_of=args.as_of)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

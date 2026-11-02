"""Publish a portable PR17 report from existing Q1 and Q2--Q6 final tables."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from research_core.pattern_scan_report_v1 import export_q1_report_data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--q1-root", type=Path, required=True, help="Existing directory containing all 12 Q1 family results")
    parser.add_argument("--remaining-root", type=Path, required=True, help="Existing Q2--Q6 result root; only completed phases are presented")
    parser.add_argument("--output", type=Path, required=True, help="New report/data directory to create")
    parser.add_argument("--as-of", required=True, help="Report date in YYYY-MM-DD form")
    parser.add_argument("--split-scripts", action="store_true", help="Write ordered classic JS chunks below 500 KiB with scripts-manifest.json")
    parser.add_argument("--display-csv", action="store_true", help="Include CSV downloads of complete displayed table slices")
    parser.add_argument("--data-prefix", default="data", help="Report-relative download directory, e.g. data/final-v1")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    export_q1_report_data(
        args.q1_root,
        args.output,
        as_of=args.as_of,
        remaining_root=args.remaining_root,
        split_scripts=args.split_scripts,
        display_csv=args.display_csv,
        data_prefix=args.data_prefix,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

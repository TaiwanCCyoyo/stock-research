"""Run the owner-authorized bounded L1 checkpoint pilot."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from research_core.pattern_scan_recovery_pilot_v1 import launch_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-root", type=Path, required=True)
    parser.add_argument("--code", action="append", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    result = launch_pilot(args.stock_root, codes=tuple(args.code), run_id=args.run_id, owner=args.owner, repo_root=Path(__file__).resolve().parents[1])
    sys.stdout.write(f"{result}\n")


if __name__ == "__main__":
    main()

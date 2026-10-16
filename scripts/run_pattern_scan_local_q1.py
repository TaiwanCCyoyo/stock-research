"""Reduce original PR17 Q1 in a worktree without persisting expanded events."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from research_core.pattern_scan_local_q1_v1 import run_local_q1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reuse-event-root", type=Path, action="append", default=[])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_local_q1(args.stock_result, args.output, repo_root=Path(__file__).resolve().parents[1], reuse_event_roots=tuple(args.reuse_event_root))


if __name__ == "__main__":
    main()

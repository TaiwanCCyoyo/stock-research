"""Prepare a local feature candidate from completed PR17 stock checkpoints."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from research_core.pattern_scan_feature_preview_v1 import build_preview


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stock-result", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--code", action="append", help="Optional bounded stock selection for inspection")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    build_preview(
        arguments.stock_result,
        arguments.destination,
        repo_root=Path(__file__).resolve().parents[1],
        codes=None if arguments.code is None else tuple(arguments.code),
    )


if __name__ == "__main__":
    main()

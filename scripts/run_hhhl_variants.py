"""Thin fresh-interpreter entry point for the approved fixed HHHL study."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from io import TextIOWrapper
from pathlib import Path
from typing import cast


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, default=Path("D:/Project/stock-research"))
    parser.add_argument("--pins", type=Path, default=root / "tasks/20261012-hhhl-v4-variants/params/input-pins-v1.json")
    parser.add_argument("--publication", type=Path, default=root / "tasks/20261012-hhhl-v4-variants/publication-v1")
    parser.add_argument("--approved-mission-merge", required=True)
    args = parser.parse_args()
    # Only this process changes its bytecode boundary: no global setting or
    # cache is changed. A nonexistent task-local prefix cannot yield stale pyc.
    sys.pycache_prefix = str(root / ".tmp" / "hhhl-variants-fresh" / uuid.uuid4().hex)
    sys.dont_write_bytecode = True
    for stream in (sys.stdout, sys.stderr):
        cast(TextIOWrapper, stream).reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("research_core.hhhl_v4_source").setLevel(logging.WARNING)
    from research_core.hhhl_variants_run import execute

    receipt = execute(args.primary, args.pins, args.publication, args.approved_mission_merge)
    print(json.dumps(receipt, ensure_ascii=False, allow_nan=False))  # noqa: T201 - CLI receipt
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

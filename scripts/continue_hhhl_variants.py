"""Thin fresh-interpreter entry point for identical-specification continuation."""

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
    parser.add_argument("--cache-source", type=Path, required=True)
    parser.add_argument("--seal-stopped-writer", type=Path, help="Operator stop evidence JSON; seal cache instead of executing")
    args = parser.parse_args()
    sys.pycache_prefix = str(root / ".tmp" / "hhhl-variants-fresh" / uuid.uuid4().hex)
    sys.dont_write_bytecode = True
    for stream in (sys.stdout, sys.stderr):
        cast(TextIOWrapper, stream).reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("research_core.hhhl_v4_source").setLevel(logging.WARNING)
    from research_core.artifact_store import read_json
    from research_core.hhhl_variants_continue_v1 import cache_seal, execute_cached
    from research_core.hhhl_variants_run import implementation_receipt

    if args.seal_stopped_writer:
        implementation_receipt(args.approved_mission_merge)
        receipt = cache_seal(args.primary, args.cache_source, args.pins, read_json(args.seal_stopped_writer))
        result = {"schema_version": receipt["schema_version"], "daily_shards": len(receipt["artifacts"])}
    else:
        result = execute_cached(args.primary, args.pins, args.publication, args.approved_mission_merge, args.cache_source)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))  # noqa: T201 - CLI receipt
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

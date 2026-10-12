"""Metadata-only feature plans/queries and the fixed invented-input benchmark."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from research_core.artifact_store import read_json
from research_core.feature_benchmark_v1 import run_synthetic_benchmark
from research_core.feature_block_store_v1 import FeatureBlockStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="Inspect exact identities without calculations")
    plan.add_argument("--store", type=Path, required=True)
    plan.add_argument("--identities", type=Path, required=True, help="JSON object with an identities array")
    query = commands.add_parser("query", help="Verify and return metadata for one identity")
    query.add_argument("--store", type=Path, required=True)
    query.add_argument("--identity", type=Path, required=True)
    benchmark = commands.add_parser("benchmark-synthetic", help="Run only the preregistered invented-input benchmark")
    benchmark.add_argument("--output", type=Path, required=True, help="Explicit absolute nonexistent scratch directory")
    args = parser.parse_args(argv)
    if args.command == "benchmark-synthetic":
        receipt = run_synthetic_benchmark(args.output)
        result = {
            "schema": receipt["schema"],
            "complete": receipt["complete"],
            "receipt": str(args.output / "receipt.json"),
            "comparisons": receipt["comparisons"],
            "parity": receipt["parity"],
        }
    else:
        store = FeatureBlockStore(args.store)
        if args.command == "plan":
            packet = read_json(args.identities)
            if not isinstance(packet.get("identities"), list):
                raise ValueError("Plan requires an identities array")
            result = {"schema": "research-feature-plan.v1", "blocks": store.plan(packet["identities"])}
        else:
            result = {"schema": "research-feature-query.v1", "block": store.inspect(read_json(args.identity))}
    sys.stdout.write(json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())

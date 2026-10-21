"""Independently reconstruct five declared candidates from one completed scan."""

import argparse
import json
import logging
import sys
from pathlib import Path

from research_core.artifact_store import file_digest
from research_core.pattern_scan_candidate_audit_run_v4 import audit_computed_scan
from research_core.research_data_paths import DataRoots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--computed-results", type=Path, required=True)
    parser.add_argument("--stock-reference", type=Path)
    parser.add_argument("--output-id", required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    descriptor = {"path": str(args.computed_results), "sha256": file_digest(args.computed_results)}
    receipt = audit_computed_scan(
        DataRoots(args.primary_root, args.data_root),
        computed_results=descriptor,
        run_root=args.run_root,
        stock_reference=args.stock_reference,
        output_id=args.output_id,
    )
    sys.stdout.write(json.dumps({key: receipt[key] for key in ("audit_complete", "selected_candidate_n", "aggregate_checks", "output_path")}) + "\n")


if __name__ == "__main__":
    main()

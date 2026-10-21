"""Thin fixed-input pattern-scan command; the library owns its workflow."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from research_core.pattern_scan_run_v1 import launch
from research_core.research_data_paths import DataRoots


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("profile", "stock", "all"))
    parser.add_argument("--primary-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--input-manifest-sha256", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--calculation-authorized", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    receipt = launch(
        DataRoots(args.primary_root, args.data_root),
        mode=args.mode,
        input_manifest_sha256=args.input_manifest_sha256,
        run_id=args.run_id,
        profile_path=args.profile,
        calculation_authorized=args.calculation_authorized,
    )
    sys.stdout.write(
        json.dumps({"complete": receipt["complete"], "source_id": receipt["source_id"], "phase": receipt["result"]["phase"]}, ensure_ascii=False) + "\n"
    )


if __name__ == "__main__":
    main()

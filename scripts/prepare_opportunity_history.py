"""Pin explicitly selected local files and export descriptive price series."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research_core.opportunity_history_inputs import (
    ACTION_HASH,
    PRICE_HASH,
    export_series,
    require_empty_target,
    snapshot_inputs,
)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mapping-path", required=True, type=Path)
    parser.add_argument("--taxonomy-path", type=Path)
    parser.add_argument("--expected-price-hash", default=PRICE_HASH)
    parser.add_argument("--expected-actions-hash", default=ACTION_HASH)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    require_empty_target(args.snapshot_dir)
    require_empty_target(args.output_dir)
    if (
        args.snapshot_dir.resolve() == args.output_dir.resolve()
        or args.snapshot_dir.resolve() in args.output_dir.resolve().parents
        or args.output_dir.resolve() in args.snapshot_dir.resolve().parents
    ):
        parser.error("Snapshot and output directories must be disjoint")
    paths = {name: args.source_dir / name for name in ("price_daily.parquet", "corporate_actions.sqlite", "symbol_meta.sqlite")}
    paths["stock_symbol_mapping.json5"] = args.mapping_path
    if args.taxonomy_path:
        paths["value_chain_classification.json"] = args.taxonomy_path
    snapshot_inputs(
        paths,
        args.snapshot_dir,
        {
            "price_daily.parquet": args.expected_price_hash,
            "corporate_actions.sqlite": args.expected_actions_hash,
        },
    )
    manifest = export_series(args.snapshot_dir, args.output_dir)
    sys.stdout.write(
        json.dumps(
            {"count": manifest["count"], "calendar_id": manifest["calendar_id"], "manifest": str(args.output_dir / "series-manifest.json")}, ensure_ascii=True
        )
        + "\n"
    )


if __name__ == "__main__":
    main()

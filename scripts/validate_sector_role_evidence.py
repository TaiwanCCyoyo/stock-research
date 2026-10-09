"""CLI for validating an additive sector-role evidence packet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from research_core.sector_role_evidence import validate_packet


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("packet", type=Path)
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--write-receipt", type=Path)
    args = parser.parse_args()
    if args.receipt is not None and args.write_receipt is not None:
        parser.error("--receipt and --write-receipt cannot be used together")
    if args.write_receipt is not None:
        output = args.write_receipt.resolve()
        if output == args.packet.resolve() or output.is_relative_to(args.catalog.resolve()):
            parser.error("receipt output overlaps packet or catalog artifacts")
        if output.exists() or output.is_symlink():
            parser.error("receipt output already exists; choose a new authoring path")
    summary = validate_packet(args.packet, args.catalog, args.receipt)
    payload = json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if args.write_receipt is not None:
        with args.write_receipt.open("x", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()

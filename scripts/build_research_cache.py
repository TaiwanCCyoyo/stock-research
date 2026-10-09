"""Explicit build/verify of Stock's immutable derived cache (no downloads)."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from research_core.derived_cache import build_cache, verify_cache


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("prices", "actions", "calendar", "root"):
        build.add_argument(f"--{name}", required=True, type=Path)
    build.add_argument("--cutoff", required=True)
    build.add_argument("--codes", nargs="+")
    verify = sub.add_parser("verify")
    verify.add_argument("version", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = (
        verify_cache(args.version)
        if args.command == "verify"
        else build_cache(prices=args.prices, actions=args.actions, calendar=args.calendar, root=args.root, cutoff=args.cutoff, codes=args.codes)
    )
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))  # noqa: T201 - CLI receipt on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

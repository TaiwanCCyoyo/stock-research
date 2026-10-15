"""Discover, register and verify pinned shared research data; never auto-compute."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from research_core.artifact_store import read_json
from research_core.research_data_catalog import DataCatalog, read_market_context
from research_core.research_data_paths import DataRoots


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    sub.add_parser("register-existing")
    register = sub.add_parser("register")
    register.add_argument("packet", type=Path, help="JSON object containing entries")
    query = sub.add_parser("verify")
    query.add_argument("data_id")
    query.add_argument("version_id")
    query.add_argument("--manifest-sha256", required=True)
    context = sub.add_parser("context")
    context.add_argument("version_id")
    context.add_argument("--manifest-sha256", required=True)
    context.add_argument("--layer", choices=("past_only", "retrospective"), required=True)
    retire = sub.add_parser("retire", help="stop advertising one version; payload deletion is a separate step")
    retire.add_argument("data_id")
    retire.add_argument("version_id")
    retire.add_argument("--manifest-sha256", required=True)
    retire.add_argument("--reason", required=True)
    retire.add_argument("--retired-on", required=True, help="ISO date of the owner's approval")
    guard = sub.add_parser("check-worktree")
    guard.add_argument("path", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    roots = DataRoots.from_env()
    catalog = DataCatalog(roots)
    result: Any
    if args.command == "catalog":
        result = catalog.read()
    elif args.command == "register-existing":
        from research_core.research_data_legacy import register_existing

        result = register_existing(catalog)
    elif args.command == "register":
        result = catalog.register(read_json(args.packet)["entries"])
    elif args.command == "verify":
        result = catalog.get(args.data_id, args.version_id, manifest_sha256=args.manifest_sha256)
    elif args.command == "retire":
        result = catalog.retire(args.data_id, args.version_id, manifest_sha256=args.manifest_sha256, reason=args.reason, retired_on=args.retired_on)
    elif args.command == "context":
        result = read_market_context(catalog, args.version_id, args.manifest_sha256, layer=args.layer)
    else:
        roots.validate_worktree(args.path)
        result = {"worktree": str(args.path), "isolation": "verified", "shared_root": str(roots.data)}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))  # noqa: T201 - CLI protocol
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

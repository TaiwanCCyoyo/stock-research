"""Explicit additive Stock research backup, verify and new-folder restore."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from research_core.artifact_backup import backup_sources, default_sources, restore_backup, verify_backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("--project", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)
    backup.add_argument(
        "--frozen-sqlite", action="append", default=[], metavar="PATH=SEALED_SHA256", help="Explicit closed historical input only; live SQLite is never copied"
    )
    verify = sub.add_parser("verify")
    verify.add_argument("manifest", type=Path)
    restore = sub.add_parser("restore")
    restore.add_argument("manifest", type=Path)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.command == "backup":
        frozen = {Path(item.rsplit("=", 1)[0]): item.rsplit("=", 1)[1] for item in args.frozen_sqlite}
        result = backup_sources(default_sources(args.project), args.destination, frozen_sqlite=frozen)
    elif args.command == "verify":
        result = verify_backup(args.manifest)
    else:
        result = restore_backup(args.manifest, args.destination)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))  # noqa: T201 - CLI receipt on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

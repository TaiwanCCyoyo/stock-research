"""Register, inspect or retire an explicitly selected development preview."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

from research_core.development_previews import PreviewError, list_previews, open_preview, register, retire


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    registration = subparsers.add_parser("register")
    registration.add_argument("--id", required=True)
    registration.add_argument("--title", required=True)
    registration.add_argument("--route", required=True)
    registration.add_argument("--worktree", type=Path, default=Path.cwd())
    registration.add_argument("--pr", type=int)
    for command in ("open", "retire"):
        child = subparsers.add_parser(command)
        child.add_argument("--id", required=True)
    subparsers.add_parser("list")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        if args.command == "register":
            result = asdict(register(identifier=args.id, title=args.title, route=args.route, worktree=args.worktree, pr=args.pr))
        elif args.command == "retire":
            retire(args.id)
            result = {"retired": args.id}
        elif args.command == "open":
            result = open_preview(args.id)
        else:
            result = list_previews()
    except (PreviewError, OSError) as exc:
        parser.exit(1, f"{exc}\n")
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

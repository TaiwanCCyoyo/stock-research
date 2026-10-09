"""Read-only CLI over research evidence; catalog never opens performance outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research_core.evidence import EvidenceError, exposure_status, read_json, task_catalog, validate_registry, validate_result  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    catalog = sub.add_parser("catalog")
    catalog.add_argument("--tasks-root", type=Path, default=REPO_ROOT / "tasks")
    validate = sub.add_parser("validate-result")
    validate.add_argument("path", type=Path)
    registry = sub.add_parser("registry")
    registry.add_argument("path", type=Path, nargs="?", default=REPO_ROOT / "docs/en/research-registry.json")
    exposure = sub.add_parser("exposure")
    exposure.add_argument("--registry", type=Path, default=REPO_ROOT / "docs/en/research-registry.json")
    exposure.add_argument("--scope", required=True)
    exposure.add_argument("--start", required=True)
    exposure.add_argument("--end", required=True)
    args = parser.parse_args()
    result: dict[str, Any]
    try:
        if args.command == "catalog":
            result = {"tasks": task_catalog(args.tasks_root)}
        elif args.command == "validate-result":
            value = validate_result(read_json(args.path))
            result = {"schema_valid": True, "run_id": value["run_id"], "scientific_acceptance_verified": False}
        elif args.command == "registry":
            result = validate_registry(read_json(args.path))
        else:
            result = exposure_status(read_json(args.registry), args.scope, {"start": args.start, "end": args.end})
    except (EvidenceError, ValueError) as error:
        parser.exit(2, f"{error}\n")
    print_json(result)


def print_json(value: object) -> None:
    import sys

    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()

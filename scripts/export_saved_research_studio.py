"""Create an additive presentation package from verified saved inputs, without replay."""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from pathlib import Path

from research_core.saved_research_studio import export_bundle, write_split_package

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-runs", type=Path, default=ROOT / "research_web/public/data/saved-research-runs.json.gz")
    parser.add_argument("--tasks-root", type=Path, default=ROOT / "tasks")
    parser.add_argument("--registry", type=Path, default=ROOT / "docs/en/research-registry.json")
    parser.add_argument("--benchmark-manifest", type=Path)
    parser.add_argument("--benchmark-manifest-sha")
    parser.add_argument("--presentation", type=Path, default=ROOT / "research_web/public/data/research-presentation.v1.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split-output", action="store_true", help="write a manifest and <=450 KiB binary parts, preserving gzip bytes")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.output is None:
        filename = "saved-research-studio.manifest.json" if args.split_output else "saved-research-studio.json.gz"
        args.output = ROOT / "research_web/public/data" / filename
    if args.split_output and args.output.suffix.casefold() != ".json":
        parser.error("--split-output requires a .json manifest output")
    if args.output.resolve() == args.saved_runs.resolve():
        parser.error("the old saved run package cannot be overwritten")
    if args.output.exists():
        parser.error("choose a new output path; existing presentation packages are preserved")
    package = export_bundle(args.saved_runs, args.tasks_root, args.registry, args.benchmark_manifest, args.benchmark_manifest_sha, args.presentation)
    raw = json.dumps(package, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if args.split_output:
        transport = write_split_package(gzip.compress(raw, mtime=0), args.output)
    else:
        transport = None
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as target:
            target.write(gzip.compress(raw, mtime=0) if args.output.suffix == ".gz" else raw)
    sys.stdout.write(
        json.dumps(
            {
                "schema": package["schema"],
                "output": str(args.output),
                "runs": len(package["runs"]),
                "bytes": args.output.stat().st_size,
                "transport": transport,
                "reconciliation": {run["id"]: run["reconciliation"] for run in package["runs"]},
            },
            ensure_ascii=False,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Query verified HHHL variants summaries without requiring large local inputs."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from research_core.hhhl_variants_query import filter_summary, load_event, load_summary, summary_records

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publication", type=Path, default=ROOT / "tasks/20261012-hhhl-v4-variants/publication-v1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="Verify and print publication identity and row count only")
    mode.add_argument("--event", help="Exact event ID from the pinned optional local dataset")
    parser.add_argument("--part", choices=("observations", "flags"), default="observations")
    for option in ("row-kind", "cohort", "split", "candidate", "feature", "bin", "flag", "riskset"):
        parser.add_argument(f"--{option}")
    for option in ("horizon", "landmark", "year", "limit"):
        parser.add_argument(f"--{option}", type=int)
    args = parser.parse_args(argv)
    if args.event and any(
        getattr(args, name) is not None
        for name in ("row_kind", "cohort", "split", "candidate", "feature", "bin", "flag", "riskset", "horizon", "landmark", "year")
    ):
        parser.error("--event supports --part and --limit; summary filters require summary mode")
    try:
        output: Any
        if args.event:
            output = summary_records(filter_summary(load_event(args.publication, args.event, args.part), limit=args.limit))
        elif args.verify:
            frame, receipt = load_summary(args.publication)
            output = {"schema_version": receipt["schema_version"], "dataset_id": receipt["dataset_id"], "rows": len(frame)}
        else:
            frame, _ = load_summary(args.publication)
            output = summary_records(
                filter_summary(
                    frame,
                    row_kind=args.row_kind,
                    cohort=args.cohort,
                    split=args.split,
                    candidate=args.candidate,
                    feature=args.feature,
                    bin_id=args.bin,
                    flag=args.flag,
                    riskset=args.riskset,
                    horizon=args.horizon,
                    landmark=args.landmark,
                    year=args.year,
                    limit=args.limit,
                )
            )
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"HHHL variants query failed: {error}\n")
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))  # noqa: T201 - CLI JSON output
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())

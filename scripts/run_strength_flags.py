"""Thin entrypoint for the owner-gated weakening-flags study."""

from __future__ import annotations

import argparse
import logging
import sys

from research_core.strength_flags_run_v1 import run_study


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mission-pr", type=int)
    parser.add_argument("--code-pr", type=int)
    parser.add_argument("--run", required=True, help="label under the shared scratch root")
    parser.add_argument("--owner", default="codex-strength-weakening-flags")
    parser.add_argument("--probe", action="store_true", help="measure 20 stocks; requires both owner merges")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--memory-limit-mib", type=int, default=4096)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.mission_pr is None or args.code_pr is None or args.memory_limit_mib <= 0:
        parser.error("--mission-pr, --code-pr and a positive memory limit are required")
    result = run_study(
        mission_pr=args.mission_pr,
        code_pr=args.code_pr,
        run_id=args.run,
        owner=args.owner,
        probe=args.probe,
        resume=args.resume,
        memory_limit_bytes=args.memory_limit_mib * 1024**2,
    )
    sys.stdout.write(f"{result}\n")


if __name__ == "__main__":
    main()

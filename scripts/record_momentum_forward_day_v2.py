"""Opt-in forward recorder v2. Does not install or modify scheduled tasks."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from research_core.live_producer import assert_producer_idle
from research_core.momentum_forward_run_v2 import code_identity, run
from research_core.momentum_only_v1 import pr17_codes

DEFAULT_ROOT = Path("D:/Project/stock-research/tasks/20261021-momentum-only-doubling/forward-log")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--date")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--scheduled", action="store_true")
    args = parser.parse_args()
    path = run(
        args.root,
        pr17_codes,
        day=args.date,
        scheduled=args.scheduled,
        identity=lambda: code_identity(Path(__file__).resolve().parents[1]),
        workers=args.workers,
        producer_idle=assert_producer_idle,
    )
    if path is None:
        raise SystemExit("Forward invocation not recorded; inspect attempts-v2.jsonl and attempt-journal-v2")
    logging.getLogger(__name__).info("Recorded %s", path)


if __name__ == "__main__":
    main()

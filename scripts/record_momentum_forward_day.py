"""Freeze one forward-log day for the momentum-only study.

Run by hand after the weekday 20:30 shared-data update has finished. Without `--date`
it records the current generation's as-of day (on time); with `--date` it reconstructs
an earlier day and marks it `recorded_late`. An existing day is never overwritten.

    uv run python -m scripts.record_momentum_forward_day --workers 4
    uv run python -m scripts.record_momentum_forward_day --date 2026-10-13 --workers 4
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from research_core.live_producer import assert_producer_idle
from research_core.momentum_forward_v1 import record_day
from research_core.momentum_only_v1 import pr17_codes
from research_core.run_receipt import code_identity

LOGGER = logging.getLogger(__name__)
DEFAULT_ROOT = Path("D:/Project/stock-research/tasks/20261021-momentum-only-doubling/forward-log")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="forward-log directory in the primary checkout")
    parser.add_argument("--date", help="reconstruct this earlier day (recorded_late)")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    assert_producer_idle()
    identity = code_identity()
    if identity["dirty"]:
        raise SystemExit("record from a clean commit so the frozen rows name the code that produced them")
    path = record_day(args.root, pr17_codes(), day=args.date, code_commit=identity["commit"], workers=args.workers)
    LOGGER.info("Recorded %s", path)


if __name__ == "__main__":
    main()

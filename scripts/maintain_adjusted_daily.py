"""Maintain the shared full-market adjusted daily prices and their technical tables (no downloads).

update   build a new generation (3 price bases + technical-daily.v1) from live producer data and make it current
status   print the current generation's status and the generations studies hold
hold     keep a generation through later updates while a study still reads it
release  drop a study's hold so the next update can prune that generation
measure  time N symbols x 3 bases + technical tables without writing anything
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from datetime import datetime
from datetime import time as clock_time

from research_core import maintained_adjusted_daily as family
from research_core.live_producer import ProducerBusyError, default_wait_deadline, wait_for_producer_idle
from research_core.producer_data import producer_data_root
from research_core.run_receipt import code_identity

LOGGER = logging.getLogger(__name__)


def _wait_deadline(wait_until: str | None, no_wait: bool, now: datetime | None = None) -> datetime | None:
    """Deadline for waiting on a busy producer: `--wait-until HH:MM` (Asia/Taipei), else 23:30 today; None checks once."""
    if no_wait:
        return None
    if wait_until is None:
        return default_wait_deadline(now)
    return default_wait_deadline(now, at=clock_time.fromisoformat(wait_until))


def _startup_commit() -> str:
    try:
        return str(code_identity()["commit"])
    except Exception as error:  # noqa: BLE001 - a startup line must never stop the run
        return f"unavailable ({type(error).__name__})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    update_parser = sub.add_parser("update")
    update_parser.add_argument("--wait-until", metavar="HH:MM", help="wait for a busy producer until this Asia/Taipei time (default 23:30)")
    update_parser.add_argument("--no-wait", action="store_true", help="fail at once when the producer is busy")
    update_parser.add_argument("--force", action="store_true", help="rebuild even when inputs and code are unchanged since the current generation")
    sub.add_parser("status")
    hold = sub.add_parser("hold")
    hold.add_argument("--generation", required=True)
    hold.add_argument("--holder", required=True, help="short study id, e.g. pr17-pattern-scan")
    hold.add_argument("--reason", required=True)
    release = sub.add_parser("release")
    release.add_argument("--holder", required=True)
    measure = sub.add_parser("measure")
    measure.add_argument("--codes", type=int, default=50, help="number of symbols, taken evenly across the sorted list")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    LOGGER.info("starting %s pid=%d code_commit=%s", args.command, os.getpid(), _startup_commit())
    if args.command == "update":
        try:
            wait_for_producer_idle(_wait_deadline(args.wait_until, args.no_wait))
        except ProducerBusyError:
            return 1
        result = family.update(producer_root=producer_data_root(), skip_unchanged=not args.force)
    elif args.command == "status":
        status = family.current_generation()
        result = {
            key: status[key]
            for key in ("generation", "asof", "codes", "calendar", "definition", "source_policy", "actions", "bases", "timings_seconds", "path")
        }
        technical = status.get("technical")
        result["technical"] = None if technical is None else {"definition": technical["definition"]["version"], "tables": technical["tables"]}
        result["holds"] = family.held_generations()
    elif args.command == "hold":
        result = family.hold_generation(args.generation, holder=args.holder, reason=args.reason)
    elif args.command == "release":
        result = {"released": family.release_generation(args.holder)}
    else:
        started = time.monotonic()
        bars, actions, _, _ = family.load_inputs(producer_data_root())
        loaded = time.monotonic()
        everything = sorted(bars["Code"].unique())
        step = max(1, len(everything) // args.codes)
        chosen = everything[::step][: args.codes]
        summary = family.compute(bars, actions, codes=chosen)
        elapsed = time.monotonic() - loaded
        result = {
            "symbols_measured": len(chosen),
            "symbols_total": len(everything),
            "load_seconds": round(loaded - started, 1),
            "compute_seconds": round(elapsed, 1),
            "estimated_full_compute_seconds": round(elapsed / len(chosen) * len(everything), 0),
            "rows_per_basis": {basis: tally["rows"] for basis, tally in summary["bases"].items()},
            "technical_rows": {name: tally["rows"] for name, tally in summary["technical"]["tables"].items()},
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))  # noqa: T201 - CLI receipt on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

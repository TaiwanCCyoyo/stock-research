"""Maintain the shared full-market adjusted daily prices and their technical tables (no downloads).

update   build a new generation (3 price bases + technical-daily.v1) from live producer data and make it current
status   print the current generation's status
measure  time N symbols x 3 bases + technical tables without writing anything
"""

from __future__ import annotations

import argparse
import json
import logging
import time

from research_core import maintained_adjusted_daily as family
from research_core.producer_data import producer_data_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("update")
    sub.add_parser("status")
    measure = sub.add_parser("measure")
    measure.add_argument("--codes", type=int, default=50, help="number of symbols, taken evenly across the sorted list")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.command == "update":
        result = family.update(producer_root=producer_data_root())
    elif args.command == "status":
        status = family.current_generation()
        result = {
            key: status[key]
            for key in ("generation", "asof", "codes", "calendar", "definition", "source_policy", "actions", "bases", "timings_seconds", "path")
        }
        technical = status.get("technical")
        result["technical"] = None if technical is None else {"definition": technical["definition"]["version"], "tables": technical["tables"]}
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

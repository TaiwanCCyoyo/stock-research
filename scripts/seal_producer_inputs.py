"""Seal the live producer research read-set into a pinned immutable version, or verify one.

The primary root comes from STOCK_RESEARCH_DATA_ROOT (`<primary>/research_data`); the
live source from STOCK_PRODUCER_DATA_ROOT via `producer_data_root()` unless --source.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from research_core.producer_data import producer_data_root
from research_core.producer_inputs import open_from_env, seal_producer_inputs
from research_core.research_data_paths import DataRoots

LOGGER = logging.getLogger(__name__)
# StockProject-DailyUpdate holds 18:00-18:45 on weekdays; OfficialBackfill starts 18:25.
WRITER_WINDOW = ((17, 50), (19, 0))
TASK_QUERY = "Get-ScheduledTask -TaskName 'StockProject-*' | Where-Object State -eq 'Running' | ForEach-Object TaskName"


def running_writers() -> list[str]:
    """Names of producer scheduled tasks currently running; empty off Windows."""
    if sys.platform != "win32":
        return []
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", TASK_QUERY], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"cannot read scheduled task state: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def writer_gate(now: datetime, *, allow_window: bool) -> None:
    """Refuse to read live SQLite while a producer writer runs or may start."""
    running = running_writers()
    if running:
        raise RuntimeError(f"producer writers are running: {running}; seal after they finish")
    start, end = WRITER_WINDOW
    if not allow_window and now.weekday() < 5 and start <= (now.hour, now.minute) < end:
        raise RuntimeError("inside the weekday producer write window 17:50-19:00; pass --allow-window only after checking it is idle")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("seal", help="seal the live producer read set")
    seal.add_argument("--source", type=Path, help="producer data root; default producer_data_root()")
    seal.add_argument("--no-register", action="store_true", help="do not add the version to the research_data catalog")
    seal.add_argument("--allow-window", action="store_true", help="seal inside the weekday write window after checking writers are idle")
    verify = sub.add_parser("verify", help="open a pinned version, hash every member and print its roots")
    verify.add_argument("version_id")
    verify.add_argument("--manifest-sha256", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    result: dict[str, Any]
    if args.command == "seal":
        roots = DataRoots.from_env()
        source = args.source if args.source is not None else producer_data_root()
        writer_gate(datetime.now(), allow_window=args.allow_window)
        result = seal_producer_inputs(source, roots, register=not args.no_register)
    else:
        sealed = open_from_env(args.version_id, args.manifest_sha256)
        sealed.verify_all()
        result = {"version_id": sealed.version_id, "root": str(sealed.root), "data_root": str(sealed.data_root), "files": len(sealed.names())}
    print(json.dumps(result, ensure_ascii=False))  # noqa: T201 - CLI protocol on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

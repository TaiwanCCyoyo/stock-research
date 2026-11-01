"""Freeze one forward-log day for the momentum-only study.

Run by hand after the weekday 20:30 shared-data update has finished. Without `--date`
it records the current generation's as-of day (on time); with `--date` it reconstructs
an earlier day and marks it `recorded_late`. An existing day is never overwritten.
Every run, including a refusal or a failure, appends a line to `<root>/attempts.jsonl`.
The default root is under the research-data root; a default-root run first migrates any legacy
primary-checkout `forward-log` there (copy only, legacy untouched) and refuses to record on a mismatch.
`--scheduled` is the weekday 21:00 task: it waits for today's shared generation (or
logs why it could not) instead of recording whatever generation is current.

    uv run python -m scripts.record_momentum_forward_day --workers 4
    uv run python -m scripts.record_momentum_forward_day --date 2026-10-13 --workers 4
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
from pathlib import Path

from research_core.live_producer import ProducerBusyError, assert_producer_idle
from research_core.momentum_forward_paths import ForwardLogMigrationError, resolve_forward_log_root
from research_core.momentum_forward_v1 import record_with_ledger, scheduled_record
from research_core.momentum_only_v1 import pr17_codes

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
UNCOMMITTED = "uncommitted code: record from a clean commit so the frozen rows name the code that produced them"


def _code_identity(repo: Path = REPO_ROOT) -> dict[str, str | bool]:
    """Commit and dirty flag of this checkout, ignoring the producer submodule's gitlink.

    The primary checkout usually carries a moved `stock-data-downloader` pointer; the forward
    log never runs submodule code, so only this repository's own tracked files count. The
    forward log's output lives under the research-data root, outside this checkout.
    """

    def git(*arguments: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=True).stdout.strip()

    dirty = bool(git("status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all", "--", "."))
    return {"commit": git("rev-parse", "HEAD"), "dirty": dirty}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="forward-log directory (default: the research-data root copy; a legacy primary-checkout copy is migrated first)",
    )
    parser.add_argument("--date", help="reconstruct this earlier day (recorded_late)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--scheduled", action="store_true", help="wait for today's shared generation, then record it (the weekday 21:00 task)")
    args = parser.parse_args()
    LOGGER.info("starting record_momentum_forward_day pid=%d scheduled=%s date=%s workers=%d", os.getpid(), args.scheduled, args.date, args.workers)
    try:
        root = resolve_forward_log_root(args.root)
    except ForwardLogMigrationError as error:
        LOGGER.error("%s", error)
        raise SystemExit(f"forward-log migration failed, nothing recorded: {error}") from error
    identity = _code_identity()
    LOGGER.info("code_commit=%s dirty=%s", identity["commit"], identity["dirty"])
    dirty = UNCOMMITTED if identity["dirty"] else None
    if args.scheduled:
        commit = str(identity["commit"])
        path = scheduled_record(root, pr17_codes(), code_commit=commit, workers=args.workers, producer_idle=assert_producer_idle, refusal=dirty)
        if dirty is not None:
            raise SystemExit(dirty)
        LOGGER.info("Scheduled run finished: %s", path or "not recorded")
        return
    refusal = None
    try:
        assert_producer_idle()
    except ProducerBusyError as error:
        refusal = f"producer busy: {error}"
    if refusal is None:
        refusal = dirty
    path = record_with_ledger(root, pr17_codes(), day=args.date, code_commit=str(identity["commit"]), workers=args.workers, refusal=refusal)
    if path is None:
        raise SystemExit(refusal)
    LOGGER.info("Recorded %s", path)


if __name__ == "__main__":
    main()

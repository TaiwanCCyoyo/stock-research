"""Resolve the live producer data root and read it safely; never acquire, copy or link data.

Research worktrees read the producer's live data in place, read-only. The root is
`STOCK_PRODUCER_DATA_ROOT` when set (an explicit absolute directory, no fallback when
invalid), else `<primary checkout>/stock-data-downloader/data`. The primary checkout is
found from this checkout's own `.git` file, so a linked worktree without an initialized
submodule still reads the primary's data.

Live files change during the producer's evening runs. Research reads go through
`assert_producer_idle` once per run, open SQLite read-only, and use `read_stable` so a
file rewritten during the read fails instead of being half-read.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime
from datetime import time as clock_time
from pathlib import Path
from typing import TypeVar

LOGGER = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]
# StockProject-DailyUpdate holds 18:00-18:45 on weekdays; OfficialBackfill starts at 18:25
# and, after a month rollover, runs longer, which the running-task check covers.
WRITE_WINDOW = (clock_time(18, 0), clock_time(18, 45))
TASK_QUERY = "Get-ScheduledTask -TaskName 'StockProject-*' | Where-Object State -eq 'Running' | ForEach-Object TaskName"
T = TypeVar("T")


class ProducerBusyError(RuntimeError):
    """A producer writer is running or may be writing now."""


class ProducerChangedError(RuntimeError):
    """A live producer file changed while it was being read."""


def primary_checkout(start: Path = REPO_ROOT) -> Path:
    """The primary checkout for `start`: itself, or the owner of a linked worktree's common `.git`.

    Parses `.git` and `commondir` directly instead of running `git`, so it costs no
    subprocess. A checkout without `.git` (a container image) or a submodule's `.git`
    file resolves to `start` itself.
    """
    marker = start / ".git"
    if not marker.is_file():
        return start
    text = marker.read_text(encoding="utf-8").strip()
    if not text.startswith("gitdir:"):
        raise ValueError(f"unrecognized .git file: {marker}")
    admin = Path(text.removeprefix("gitdir:").strip())
    admin = admin if admin.is_absolute() else start / admin
    common_file = admin / "commondir"
    if not common_file.is_file():
        return start
    common = Path(common_file.read_text(encoding="utf-8").strip())
    common = (common if common.is_absolute() else admin / common).resolve()
    if common.name != ".git" or not common.is_dir():
        raise ValueError(f"linked worktree has no primary .git directory: {common}")
    return common.parent


def producer_data_root() -> Path:
    configured = os.environ.get("STOCK_PRODUCER_DATA_ROOT")
    if configured is None:
        return primary_checkout() / "stock-data-downloader" / "data"
    root = Path(configured)
    if not configured.strip() or not root.is_absolute():
        raise ValueError("STOCK_PRODUCER_DATA_ROOT must be an absolute directory path")
    if not root.is_dir():
        raise FileNotFoundError(f"STOCK_PRODUCER_DATA_ROOT directory is unavailable: {root}; no automatic fallback")
    return root.resolve()


def in_write_window(now: datetime) -> bool:
    start, end = WRITE_WINDOW
    return now.weekday() < 5 and start <= now.time() < end


def running_producer_tasks() -> list[str]:
    """Names of `StockProject-*` scheduled tasks now running; empty off Windows."""
    if sys.platform != "win32":
        return []
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", TASK_QUERY], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ProducerBusyError(f"cannot read producer scheduled-task state: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def assert_producer_idle(now: datetime | None = None) -> None:
    """Refuse a research read of live producer data while a writer runs or may run."""
    moment = datetime.now() if now is None else now
    if in_write_window(moment):
        raise ProducerBusyError("inside the weekday producer write window 18:00-18:45; read live producer data outside it")
    running = running_producer_tasks()
    if running:
        raise ProducerBusyError(f"producer writers are running: {running}")
    LOGGER.debug("Producer idle at %s", moment.isoformat(timespec="seconds"))


def readonly_sqlite(path: Path) -> sqlite3.Connection:
    """Read-only connection; on a WAL database SQLite may still create its own -shm/-wal files."""
    if not path.is_file():
        raise FileNotFoundError(f"SQLite input missing: {path}")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)


def read_stable(path: Path, read: Callable[[Path], T]) -> T:
    """Run `read(path)` and fail if the file's size or mtime changed meanwhile."""
    before = path.stat()
    value = read(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ProducerChangedError(f"producer file changed during read: {path}")
    return value

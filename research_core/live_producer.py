"""Guards for research reads of the live producer data; never acquire, copy or link data.

Research worktrees read the live producer root in place (`producer_data.producer_data_root()`,
which owns root discovery). Its files change during the producer's evening runs, so a
research run calls `assert_producer_idle` before reading, opens SQLite read-only, uses
`read_stable` so a file rewritten mid-read fails, and `run_receipt.write_run_receipt`
re-checks every fingerprinted input at the end so a writer that ran during the study is
caught rather than mixing old and new files silently.
"""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from datetime import time as clock_time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, TypeVar

LOGGER = logging.getLogger(__name__)
# StockProject-DailyUpdate holds 18:00-18:45 on weekdays; OfficialBackfill starts at 18:25
# and, after a month rollover, runs longer, which the running-task check covers.
WRITE_WINDOW = (clock_time(18, 0), clock_time(18, 45))
# The scheduled tasks run on Taiwan time. Taiwan has no daylight saving, so a fixed
# UTC+08:00 offset is exact and needs no tz database on Windows.
PRODUCER_TZ = timezone(timedelta(hours=8), "Asia/Taipei")
TASK_QUERY = "Get-ScheduledTask -TaskName 'StockProject-*' | Where-Object State -eq 'Running' | ForEach-Object TaskName"
T = TypeVar("T")


class ProducerBusyError(RuntimeError):
    """A producer writer is running or may be writing now."""


class ProducerChangedError(RuntimeError):
    """A live producer file changed while a run was reading it."""


def producer_time(now: datetime | None = None) -> datetime:
    """`now` on the producer schedule's clock; a naive timestamp is ambiguous and refused."""
    if now is None:
        return datetime.now(PRODUCER_TZ)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required; the producer schedule runs on Asia/Taipei (UTC+08:00)")
    return now.astimezone(PRODUCER_TZ)


def in_write_window(now: datetime) -> bool:
    start, end = WRITE_WINDOW
    local = producer_time(now)
    return local.weekday() < 5 and start <= local.time() < end


def running_producer_tasks() -> list[str]:
    """Names of `StockProject-*` scheduled tasks now running; empty off Windows."""
    if sys.platform != "win32":
        return []
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", TASK_QUERY], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ProducerBusyError(f"cannot read producer scheduled-task state: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def assert_producer_idle(now: datetime | None = None) -> None:
    """Refuse a research read of live producer data while a writer runs or may run.

    A point-in-time probe: pair it with an end-of-run check of the inputs read.
    """
    moment = producer_time(now)
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


def stat_identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    return info.st_size, info.st_mtime_ns


def read_stable(path: Path, read: Callable[[Path], T]) -> T:
    """Run `read(path)` and fail if the file's size or mtime changed meanwhile."""
    before = stat_identity(path)
    value = read(path)
    if stat_identity(path) != before:
        raise ProducerChangedError(f"producer file changed during read: {path}")
    return value


def readonly_connect(database: str | Path, timeout: float = 30.0, **_: Any) -> sqlite3.Connection:
    """Drop-in for `sqlite3.connect` that opens an existing database read-only.

    A read-write connection is not harmless on a live WAL database: the last connection to
    close checkpoints the WAL into the main file, which writes producer data.
    """
    return sqlite3.connect(Path(database).resolve().as_uri() + "?mode=ro", uri=True, timeout=timeout)


@contextmanager
def sqlite_reads_readonly(module: ModuleType) -> Iterator[None]:
    """Route `module.sqlite3.connect` to `readonly_connect` for the duration of the block.

    For code whose bytes are SHA-pinned evidence (for example `StockProject.engine.data_loader`),
    so its reads become read-only without editing the file.
    """
    original = getattr(module, "sqlite3")  # noqa: B009 - attribute named by the pinned module
    shim = SimpleNamespace(**{name: getattr(sqlite3, name) for name in dir(sqlite3) if not name.startswith("__")})
    shim.connect = readonly_connect
    setattr(module, "sqlite3", shim)  # noqa: B010
    try:
        yield
    finally:
        setattr(module, "sqlite3", original)  # noqa: B010

"""Guards for research reads of the live producer data; never acquire, copy or link data.

Research worktrees read the live producer root in place (`producer_data.producer_data_root()`,
which owns root discovery). Its files change during the producer's evening runs, so a
research run calls `assert_producer_idle` before reading, opens SQLite read-only, uses
`read_stable` so a file rewritten mid-read fails, and `run_receipt.write_run_receipt`
re-checks every fingerprinted input at the end: a writer that ran during the study is
recorded as `inputs_changed_during_run` with the finished result kept, so a mix of old
and new files is never silent.

The scheduled-task state alone is not proof that no producer writer exists: on 2026-10-29
`StockProject-DailyUpdate` hit its Task Scheduler time limit and went back to Ready while its
python process (`run_daily.py`) lived on as an orphan for another half hour. The guard
therefore also refuses while a producer lock file (`.run_daily.lock`,
`.official_backfill.lock`) names a running pid, or (Windows) while a python/uv process
whose command line runs `run_daily.py` or `backfill_official_history.py` exists. A lock
whose pid is gone is stale: it logs a warning and does not block.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from datetime import time as clock_time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, TypeVar

from research_core.producer_data import producer_data_root

LOGGER = logging.getLogger(__name__)
# StockProject-DailyUpdate holds 18:00-18:45 on weekdays; OfficialBackfill starts at 18:25
# and, after a month rollover, runs longer, which the running-task check covers.
WRITE_WINDOW = (clock_time(18, 0), clock_time(18, 45))
# The scheduled tasks run on Taiwan time. Taiwan has no daylight saving, so a fixed
# UTC+08:00 offset is exact and needs no tz database on Windows.
PRODUCER_TZ = timezone(timedelta(hours=8), "Asia/Taipei")
TASK_QUERY = "Get-ScheduledTask -TaskName 'StockProject-*' | Where-Object State -eq 'Running' | ForEach-Object TaskName"
# Lock files the producer's writers keep in its data directory: {"pid": ..., "started_at": ...}.
PRODUCER_LOCK_NAMES = (".run_daily.lock", ".official_backfill.lock")
# Orphans outlive their scheduled task, so also look for the writer scripts' processes. Only
# python/uv processes count: a shell or editor merely mentioning a script name is not a writer.
PROCESS_QUERY = (
    r"Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.Name -match '^(python|pythonw|uv)(\.exe)?$' "
    r"-and $_.CommandLine -match 'run_daily\.py|backfill_official_history\.py' } "
    "| ForEach-Object { '{0} {1}' -f $_.ProcessId, $_.Name }"
)
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


def running_producer_tasks(*, timeout: float | None = None) -> list[str]:
    """Names of `StockProject-*` scheduled tasks now running; empty off Windows."""
    if sys.platform != "win32":
        return []
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", TASK_QUERY],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise ProducerBusyError("producer scheduled-task query timed out") from error
    if result.returncode != 0:
        raise ProducerBusyError(f"cannot read producer scheduled-task state: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _powershell_writer_processes(timeout: float | None) -> list[tuple[int, str]]:
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", PROCESS_QUERY],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as error:
        raise ProducerBusyError("producer process query timed out") from error
    if result.returncode != 0:
        raise ProducerBusyError(f"cannot read producer process list: {result.stderr.strip()}")
    found: list[tuple[int, str]] = []
    for line in result.stdout.splitlines():
        pid_text, _, name = line.strip().partition(" ")
        if pid_text.isdigit():
            found.append((int(pid_text), name or "process"))
    return found


def query_writer_processes(*, timeout: float | None = None) -> list[tuple[int, str]]:
    """(pid, name) of live python/uv processes running a producer writer script; empty off Windows."""
    if sys.platform != "win32":
        return []
    return _powershell_writer_processes(timeout)


def _pid_is_running(pid: int) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined,unused-ignore]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            # Access denied means the process exists but is not ours to query.
            return ctypes.get_last_error() == 5
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code)):
                # The process exists (we hold a handle) but its state is unknown: never call it exited.
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_lock_writers(root: Path) -> list[tuple[int, str]]:
    """(pid, lock file) for each producer lock in `root` whose recorded pid is running.

    A lock naming a pid that is gone is stale: logged, never blocking. An unreadable lock
    carries no pid to test, so it is reported at WARNING and does not block either; the
    process query is the independent check.
    """
    live: list[tuple[int, str]] = []
    for name in PRODUCER_LOCK_NAMES:
        path = root / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue  # a released lock: the producer clears its record rather than deleting the file
            pid = json.loads(text).get("pid")
        except (OSError, ValueError, AttributeError) as error:
            LOGGER.warning("Unreadable producer lock %s (%s); ignoring it", path, error)
            continue
        if _pid_is_running(pid):
            live.append((pid, name))
        else:
            LOGGER.warning("Stale producer lock %s (pid %s not running); not blocking", path, pid)
    return live


def assert_producer_idle(now: datetime | None = None, *, task_timeout: float | None = None) -> None:
    """Refuse a research read of live producer data while a writer runs or may run.

    Refuses inside the write window, while a `StockProject-*` task runs, and while a producer
    writer process is alive even if its task is no longer Running (a producer lock file with a
    running pid, or a python/uv process running `run_daily.py` or
    `backfill_official_history.py`). A stale lock does not block.

    A point-in-time probe: pair it with an end-of-run check of the inputs read.
    """
    moment = producer_time(now)
    if in_write_window(moment):
        raise ProducerBusyError("inside the weekday producer write window 18:00-18:45; read live producer data outside it")
    running = running_producer_tasks() if task_timeout is None else running_producer_tasks(timeout=task_timeout)
    if running:
        raise ProducerBusyError(f"producer writers are running: {running}")
    try:
        root: Path | None = producer_data_root()
    except (ValueError, OSError, RuntimeError) as error:
        LOGGER.debug("Producer root unavailable, skipping lock files: %s", error)
        root = None
    writers = [f"pid {pid} (lock {name})" for pid, name in ([] if root is None else live_lock_writers(root))]
    processes = query_writer_processes() if task_timeout is None else query_writer_processes(timeout=task_timeout)
    writers += [f"pid {pid} ({name} process running a producer script)" for pid, name in processes]
    if writers:
        raise ProducerBusyError(f"producer writer processes are alive: {'; '.join(writers)}")
    LOGGER.debug("Producer idle at %s", moment.isoformat(timespec="seconds"))


def default_wait_deadline(now: datetime | None = None, *, at: clock_time = clock_time(22, 0)) -> datetime:
    """`at` (default 22:00) on `now`'s Asia/Taipei day.

    22:00 bounds the wait only: it leaves the 20:30 task's 2h limit room for a typical ~15 minute
    rebuild, but neither the probe nor the rebuild after it has a time budget, so it does not
    guarantee the run ends inside that limit.
    """
    return producer_time(now).replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)


def wait_for_producer_idle(
    deadline: datetime | None,
    *,
    poll_seconds: float = 300.0,
    check: Callable[[], None] = assert_producer_idle,
    clock: Callable[[], datetime] = producer_time,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Poll `check` until the producer is idle or `deadline` passes; `None` checks once.

    Logs one INFO line per wait. The last wait is shortened to end at the deadline, where one
    final check runs, so a producer that turns idle just before the deadline is not missed.
    Still busy at the deadline, the last `ProducerBusyError` is logged at ERROR and re-raised,
    so a scheduled run exits non-zero instead of silently skipping.
    """
    label = "none" if deadline is None else producer_time(deadline).strftime("%H:%M")
    while True:
        try:
            check()
            return
        except ProducerBusyError as error:
            remaining = 0.0 if deadline is None else (deadline - clock()).total_seconds()
            if remaining <= 0:
                LOGGER.error("producer still busy (%s) at deadline %s; giving up", error, label)
                raise
            wait = min(poll_seconds, remaining)
            LOGGER.info("producer busy (%s); next check in %.0fs, deadline %s", error, wait, label)
            sleep(wait)


def readonly_sqlite(path: Path, *, timeout: float = 30.0) -> sqlite3.Connection:
    """Read-only connection; on a WAL database SQLite may still create its own -shm/-wal files."""
    if not path.is_file():
        raise FileNotFoundError(f"SQLite input missing: {path}")
    return sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=timeout)


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

"""Experiment scratch runs on the shared root, labelled so any session knows what may be cleaned.

Owner decision 2026-10-24 (docs/en/decision-records/2026-10-24-data-homes-and-scratch.md):
an experiment's intermediate files (per-stock parts, checkpoints, resume state) live in
``<shared root>/scratch/<task-id>/<run-id>/`` outside every checkout, never in a worktree's
``.tmp/``. Each run directory carries ``run.json`` written only through this module, so a
later session decides from the label instead of guessing how far the run got:

- ``running``    the experiment is computing or paused and may be resumed;
- ``complete``   the computation finished (research-program.md#delivery-states 研究完成);
- ``delivered``  its final results were moved to a durable home (成果交付);
- ``abandoned``  the owner or the task gave it up, with a reason.

"Safe to clean" (可安全清理) is derived by `survey`, never stored: delivered runs whose
recorded results still exist, and abandoned runs. A run in use holds ``.writer.lock`` with
an OS lock for its whole lifetime; the OS drops the lock when the process ends, so a live
run is never classified by a pid or a clock. ``updated_at`` only flags runs nobody touched
for `STALE_AFTER` so the owner can decide.

Final results never stay here. Delivery records where they went: a repository-relative
path committed to Git, or an absolute path elsewhere on the shared root.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any

from research_core.artifact_store import canonical, relative_name, release_os_lock, try_os_lock
from research_core.producer_data import REPO_ROOT
from research_core.research_data_paths import check_tree, checked_path
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)

SCHEMA = "scratch-run.v1"
RUN_FILE = "run.json"
LOCK_FILE = ".writer.lock"
LOCK_MARKER = b"scratch-run-lock-v1\n"
STATES = ("running", "complete", "delivered", "abandoned")
TRANSITIONS = {
    "running": {"running", "complete", "abandoned"},
    "complete": {"delivered", "abandoned"},
    "delivered": set(),
    "abandoned": set(),
}
STALE_AFTER = timedelta(days=7)
TASK_PATTERN = re.compile(r"^[0-9]{8}-[a-z0-9][a-z0-9-]*$")
RUN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

# Survey verdicts. Only DELETABLE is removed by `clean`; the rest are reported.
IN_USE, PAUSED, AWAITING_DELIVERY, DELETABLE, ASK_OWNER = "in-use", "paused", "awaiting-delivery", "deletable", "ask-owner"


class ScratchRunError(RuntimeError):
    """A scratch run is missing, malformed, busy or asked for a forbidden transition."""


def scratch_root(*, environ: Mapping[str, str] | None = None, repo_root: Path | None = None) -> Path:
    """``<shared root>/scratch``, created on first use; the shared root itself has no fallback."""
    root = checked_path(shared_data_root(environ=environ, repo_root=repo_root) / "scratch")
    root.mkdir(exist_ok=True)
    return root


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_dir(root: Path, task: str, run: str) -> Path:
    if not TASK_PATTERN.match(task):
        raise ScratchRunError(f"task id must look like 20261024-some-task, got {task!r}")
    if not RUN_PATTERN.match(run):
        raise ScratchRunError(f"run id must be lowercase letters, digits, '.', '_' or '-', got {run!r}")
    return checked_path(root / task / run)


def _lock(directory: Path) -> IO[bytes]:
    lock = directory / LOCK_FILE
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as created:
            created.write(LOCK_MARKER)
    handle = lock.open("a+b")
    if not try_os_lock(handle):
        handle.close()
        raise ScratchRunError(f"scratch run is in use by another process: {directory}")
    return handle


def _unlock(handle: IO[bytes]) -> None:
    release_os_lock(handle)
    handle.close()


def _write_record(directory: Path, record: dict[str, Any]) -> None:
    """Replace run.json atomically; readers never see a partial label."""
    temporary = directory / f".run-{os.getpid()}-{uuid.uuid4().hex}.json"
    with temporary.open("xb") as stream:
        stream.write(canonical(record))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, directory / RUN_FILE)


def read_run(directory: Path) -> dict[str, Any]:
    """Read and validate a run label without taking its lock."""
    path = checked_path(directory) / RUN_FILE
    try:
        record = json.loads(path.read_bytes())
    except FileNotFoundError as error:
        raise ScratchRunError(f"no {RUN_FILE} in {directory}") from error
    except (OSError, ValueError) as error:
        raise ScratchRunError(f"unreadable {RUN_FILE} in {directory}: {error}") from error
    if not isinstance(record, dict) or record.get("schema") != SCHEMA or record.get("state") not in STATES:
        raise ScratchRunError(f"{path} is not a {SCHEMA} label")
    if record.get("task") != directory.parent.name or record.get("run") != directory.name:
        raise ScratchRunError(f"{path} names {record.get('task')}/{record.get('run')}, not its own directory")
    return record


class ScratchRun:
    """An open scratch run holding its writer lock; use it as a context manager."""

    def __init__(self, directory: Path, record: dict[str, Any], handle: IO[bytes], repo_root: Path) -> None:
        self.path, self.record, self._repo_root = directory, record, repo_root
        self._handle: IO[bytes] | None = handle

    def __enter__(self) -> ScratchRun:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._handle is not None:
            _unlock(self._handle)
            self._handle = None

    def _save(self, **changes: Any) -> None:
        if self._handle is None:
            raise ScratchRunError(f"scratch run {self.path} is closed")
        self.record = {**self.record, **changes, "updated_at": _now()}
        _write_record(self.path, self.record)

    def heartbeat(self, *, progress: Mapping[str, Any] | None = None) -> None:
        """Record that the run is alive; `progress` ({step, total, label}) feeds the dashboard."""
        if self.record["state"] != "running":
            raise ScratchRunError(f"only a running run reports progress, this one is {self.record['state']}")
        changes: dict[str, Any] = {"pid": os.getpid(), "host": socket.gethostname()}
        if progress is not None:
            step, total, label = progress.get("step"), progress.get("total"), progress.get("label", "")
            if not isinstance(step, int) or not isinstance(total, int) or not 0 <= step <= total or not isinstance(label, str):
                raise ScratchRunError(f"progress needs integers 0 <= step <= total and a text label, got {dict(progress)!r}")
            changes["progress"] = {"step": step, "total": total, "label": label}
        self._save(**changes)

    def mark(self, state: str, *, results: Iterable[str] = (), reason: str | None = None) -> None:
        """Move the run to its next state. Delivery must name where every final result went."""
        current = self.record["state"]
        if state not in TRANSITIONS.get(current, set()) or state == "running":
            raise ScratchRunError(f"cannot move a {current} run to {state!r}")
        changes: dict[str, Any] = {}
        if state == "delivered":
            delivered = [self._checked_result(result) for result in results]
            if not delivered:
                raise ScratchRunError("delivery must list where the final results went")
            changes["results"] = delivered
        if state == "abandoned":
            if not reason or not reason.strip():
                raise ScratchRunError("abandoning a run needs a reason")
            changes["reason"] = reason.strip()
        LOGGER.info("scratch run %s/%s: %s -> %s", self.record["task"], self.record["run"], current, state)
        self._save(state=state, **changes)

    def _checked_result(self, result: str) -> str:
        scratch = self.path.parent.parent
        if Path(result).is_absolute():
            target = checked_path(Path(result)).resolve()
            if target.is_relative_to(scratch.resolve()):
                raise ScratchRunError(f"a delivered result cannot stay in the scratch area: {result}")
            if not target.is_relative_to(scratch.parent.resolve()):
                raise ScratchRunError(f"an absolute result must be on the shared root {scratch.parent}: {result}")
            if not target.exists():
                raise ScratchRunError(f"delivered result does not exist: {result}")
            return str(target)
        name = relative_name(result.replace("\\", "/"))
        if not (self._repo_root / name).exists():
            raise ScratchRunError(f"repository result {name} does not exist in {self._repo_root}")
        if name.split("/")[0] in {".tmp", ".worktrees"}:
            raise ScratchRunError(f"{name} is scratch space, not a durable result")
        return name


def create_run(
    task: str,
    run: str,
    *,
    purpose: str,
    owner: str,
    depends_on: Iterable[str] = (),
    root: Path | None = None,
    repo_root: Path | None = None,
) -> ScratchRun:
    """Create a new run directory and its label; refuses an existing run id.

    `depends_on` lists absolute paths outside the run that it reads and that must not be
    cleaned while the run is not delivered or abandoned (for example an earlier phase's
    output left in place). They are recorded, not copied.
    """
    if not purpose.strip() or not owner.strip():
        raise ScratchRunError("a scratch run needs a purpose and an owner (session or agent name)")
    root = scratch_root() if root is None else checked_path(root)
    repo_root = REPO_ROOT if repo_root is None else repo_root
    directory = _run_dir(root, task, run)
    directory.parent.mkdir(exist_ok=True)
    try:
        directory.mkdir()
    except FileExistsError as error:
        raise ScratchRunError(f"scratch run already exists, resume it with open_run: {directory}") from error
    dependencies = [str(Path(path)) for path in depends_on]
    if any(not Path(path).is_absolute() for path in dependencies):
        raise ScratchRunError(f"depends_on needs absolute paths, got {dependencies!r}")
    handle = _lock(directory)
    started = _now()
    record = {
        "schema": SCHEMA,
        "task": task,
        "run": run,
        "purpose": purpose.strip(),
        "owner": owner.strip(),
        "worktree": str(repo_root.resolve()),
        "state": "running",
        "started_at": started,
        "updated_at": started,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "depends_on": dependencies,
    }
    _write_record(directory, record)
    LOGGER.info("created scratch run %s/%s at %s", task, run, directory)
    return ScratchRun(directory, record, handle, repo_root)


def open_run(task: str, run: str, *, root: Path | None = None, repo_root: Path | None = None) -> ScratchRun:
    """Resume an existing run, taking its lock; fails while another process holds it."""
    root = scratch_root() if root is None else checked_path(root)
    directory = _run_dir(root, task, run)
    if not directory.is_dir():
        raise ScratchRunError(f"no scratch run {task}/{run} under {root}")
    handle = _lock(directory)
    try:
        record = read_run(directory)
    except ScratchRunError:
        _unlock(handle)
        raise
    return ScratchRun(directory, record, handle, REPO_ROOT if repo_root is None else repo_root)


@dataclass(frozen=True)
class RunStatus:
    task: str
    run: str
    path: Path
    state: str | None
    verdict: str
    reason: str
    updated_at: str | None
    progress: dict[str, Any] | None = None


def _status(directory: Path, now: datetime) -> RunStatus:
    task, run = directory.parent.name, directory.name
    try:
        record = read_run(directory)
    except ScratchRunError as error:
        return RunStatus(task, run, directory, None, ASK_OWNER, str(error), None)
    state, updated = record["state"], record.get("updated_at")
    progress = record.get("progress") if state == "running" else None
    try:
        handle = _lock(directory)
    except ScratchRunError:
        return RunStatus(task, run, directory, state, IN_USE, "a process holds the run open", updated, progress)
    _unlock(handle)
    if state == "abandoned":
        return RunStatus(task, run, directory, state, DELETABLE, record.get("reason", ""), updated)
    if state == "delivered":
        missing = [result for result in record.get("results", []) if Path(result).is_absolute() and not Path(result).exists()]
        if missing:
            return RunStatus(task, run, directory, state, ASK_OWNER, f"delivered results are missing: {missing}", updated)
        return RunStatus(task, run, directory, state, DELETABLE, "results delivered to " + ", ".join(record.get("results", [])), updated)
    try:
        age = now - datetime.fromisoformat(str(updated))
    except (TypeError, ValueError):
        return RunStatus(task, run, directory, state, ASK_OWNER, f"unreadable updated_at {updated!r}", updated, progress)
    if age > STALE_AFTER:
        return RunStatus(task, run, directory, state, ASK_OWNER, f"untouched for {age.days} days", updated, progress)
    if state == "complete":
        return RunStatus(task, run, directory, state, AWAITING_DELIVERY, "finished; move the final results, then mark delivered", updated)
    return RunStatus(task, run, directory, state, PAUSED, "no process holds it; resume with open_run", updated, progress)


def survey(root: Path | None = None, *, now: datetime | None = None) -> list[RunStatus]:
    """Classify every directory under the scratch root; anything unexpected is for the owner."""
    root = scratch_root() if root is None else checked_path(root)
    now = datetime.now(timezone.utc) if now is None else now
    statuses = []
    for task_dir in sorted(root.iterdir()):
        if not task_dir.is_dir() or not TASK_PATTERN.match(task_dir.name):
            statuses.append(RunStatus(task_dir.name, "", task_dir, None, ASK_OWNER, "not a task directory", None))
            continue
        for run_dir in sorted(task_dir.iterdir()):
            if not run_dir.is_dir() or not RUN_PATTERN.match(run_dir.name):
                statuses.append(RunStatus(task_dir.name, run_dir.name, run_dir, None, ASK_OWNER, "not a run directory", None))
                continue
            statuses.append(_status(run_dir, now))
    return statuses


def _delete(directory: Path) -> None:
    """Remove one run while holding its lock; refuses any link or junction inside it."""
    handle = _lock(directory)
    try:
        if read_run(directory)["state"] not in {"delivered", "abandoned"}:
            raise ScratchRunError(f"{directory} changed state; not deleting")
        check_tree(checked_path(directory))
        for child in directory.iterdir():
            if child.name == LOCK_FILE:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    finally:
        _unlock(handle)
    (directory / LOCK_FILE).unlink(missing_ok=True)
    directory.rmdir()
    try:
        directory.parent.rmdir()
    except OSError:
        pass  # other runs of the same task remain


def clean(root: Path | None = None, *, apply: bool = False, now: datetime | None = None) -> list[RunStatus]:
    """Return the deletable runs; delete them only with ``apply=True``."""
    deletable = [status for status in survey(root, now=now) if status.verdict == DELETABLE]
    for status in deletable:
        if apply:
            _delete(status.path)
            LOGGER.info("deleted scratch run %s/%s (%s)", status.task, status.run, status.state)
    return deletable

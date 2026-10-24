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
recorded results still verify, and abandoned runs, provided no unfinished run depends on
them. A run in use holds ``.writer.lock`` with an OS lock for its whole lifetime; the OS
drops the lock when the process ends, so a live run is never classified by a pid or a
clock. ``updated_at`` only flags runs nobody touched for `STALE_AFTER` so the owner can decide.

Final results never stay here. Delivery records where they went together with an identity
that is re-checked before the run's checkpoints may be deleted:

- a repository path whose working-tree content equals `DEFAULT_BRANCH` (merged; nothing
  changed, untracked or ignored under it), recorded as that branch commit and the Git
  object id; later that commit must still be reachable from the branch with the same object;
- an absolute path elsewhere on the shared root, recorded as a manifest of every file's size
  and SHA-256; `survey` re-checks sizes, deletion re-checks digests.

``depends_on`` protects inputs: while a run is running or complete, every path it names,
including a path inside another scratch run, keeps the run containing it out of `clean`.
Registering a dependency and deleting a run both hold the target's ``.deps.lock``, so no
consumer can appear between the final check and the deletion.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import IO, Any

from research_core.artifact_store import canonical, file_digest, relative_name, release_os_lock, try_os_lock
from research_core.producer_data import REPO_ROOT
from research_core.research_data_paths import check_tree, checked_path
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)

SCHEMA = "scratch-run.v1"
RUN_FILE = "run.json"
LOCK_FILE = ".writer.lock"
DEPS_LOCK_FILE = ".deps.lock"
LOCK_MARKER = b"scratch-run-lock-v1\n"
STATES = ("running", "complete", "delivered", "abandoned")
TRANSITIONS = {
    "running": {"running", "complete", "abandoned"},
    "complete": {"delivered", "abandoned"},
    "delivered": set(),
    "abandoned": set(),
}
STALE_AFTER = timedelta(days=7)
DEFAULT_BRANCH = "origin/main"
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


def _lock(directory: Path, name: str = LOCK_FILE) -> IO[bytes]:
    lock = directory / name
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
        what = "in use by another process" if name == LOCK_FILE else "being cleaned or registered by another process; retry"
        raise ScratchRunError(f"scratch run is {what}: {directory}")
    return handle


def _unlock(handle: IO[bytes]) -> None:
    release_os_lock(handle)
    handle.close()


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run Git in `repo_root`; None when Git cannot run at all."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    try:
        return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=False, env=environment, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.warning("cannot run git %s in %s: %s", args[0], repo_root, error)
        return None


def _git_out(repo_root: Path, *args: str) -> str | None:
    result = _git(repo_root, *args)
    return result.stdout.strip() if result is not None and result.returncode == 0 else None


def _repository_identity(repo_root: Path, name: str) -> dict[str, str]:
    """Identity of a repository result whose working-tree content is exactly DEFAULT_BRANCH's."""
    commit = _git_out(repo_root, "rev-parse", "--verify", f"{DEFAULT_BRANCH}^{{commit}}")
    obj = _git_out(repo_root, "rev-parse", "--verify", f"{DEFAULT_BRANCH}:{name}")
    if commit is None or obj is None:
        raise ScratchRunError(f"repository result {name} is not on {DEFAULT_BRANCH}; merge it (and fetch) before marking delivered")
    path = repo_root / name
    if path.is_file():
        if _git_out(repo_root, "hash-object", "--", name) != obj:
            raise ScratchRunError(f"{name} in {repo_root} differs from {DEFAULT_BRANCH}; merge the new content before marking delivered")
    elif path.is_dir():
        changed = _git(repo_root, "diff", "--quiet", DEFAULT_BRANCH, "--", name)
        untracked = _git_out(repo_root, "ls-files", "--others", "--", name)
        if changed is None or changed.returncode != 0 or untracked is None or untracked:
            raise ScratchRunError(f"{name} in {repo_root} has content not on {DEFAULT_BRANCH} (changed, untracked or ignored files); merge it first")
    else:
        raise ScratchRunError(f"repository result {name} is missing from {repo_root}")
    return {"kind": "repository", "path": name, "commit": commit, "object": obj}


def _repository_result_kept(repo_root: Path, result: Mapping[str, Any]) -> bool:
    commit, path = str(result.get("commit")), str(result.get("path"))
    ancestor = _git(repo_root, "merge-base", "--is-ancestor", commit, DEFAULT_BRANCH)
    if ancestor is None or ancestor.returncode != 0:
        return False
    return _git_out(repo_root, "rev-parse", "--verify", f"{commit}:{path}") == result.get("object")


def _manifest(target: Path) -> dict[str, dict[str, Any]]:
    if target.is_dir():
        check_tree(target)
    files = [target] if target.is_file() else sorted(path for path in target.rglob("*") if path.is_file())
    if not files:
        raise ScratchRunError(f"delivered result {target} contains no files")
    return {(path.relative_to(target).as_posix() if path != target else "."): {"bytes": path.stat().st_size, "sha256": file_digest(path)} for path in files}


def _shared_result_kept(result: Mapping[str, Any], *, digests: bool) -> bool:
    base, files = Path(str(result.get("path"))), result.get("files") or {}
    for relative, expected in files.items():
        path = base if relative == "." else base / relative
        try:
            if path.stat().st_size != expected["bytes"]:
                return False
        except OSError:
            return False
        if digests and file_digest(path) != expected["sha256"]:
            return False
    return bool(files)


def _unverified_results(results: list[Any], repo_root: Path, *, digests: bool) -> list[str]:
    """Results that can no longer be verified; empty when every one still is."""
    lost = []
    for result in results:
        if not isinstance(result, Mapping):
            lost.append(repr(result))
        elif result.get("kind") == "repository":
            if not _repository_result_kept(repo_root, result):
                lost.append(str(result.get("path")))
        elif result.get("kind") != "shared" or not _shared_result_kept(result, digests=digests):
            lost.append(str(result.get("path")))
    return lost


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

    def _checked_result(self, result: str) -> dict[str, Any]:
        scratch = self.path.parent.parent
        if Path(result).is_absolute():
            target = checked_path(Path(result)).resolve()
            if target.is_relative_to(scratch.resolve()):
                raise ScratchRunError(f"a delivered result cannot stay in the scratch area: {result}")
            if not target.is_relative_to(scratch.parent.resolve()):
                raise ScratchRunError(f"an absolute result must be on the shared root {scratch.parent}: {result}")
            if not target.exists():
                raise ScratchRunError(f"delivered result does not exist: {result}")
            return {"kind": "shared", "path": str(target), "files": _manifest(target)}
        name = relative_name(result.replace("\\", "/")).rstrip("/")
        if name.split("/")[0] in {".tmp", ".worktrees"}:
            raise ScratchRunError(f"{name} is scratch space, not a durable result")
        return _repository_identity(self._repo_root, name)


def _owning_run(root: Path, path: Path) -> Path | None:
    """The scratch run directory that contains `path`, if any."""
    resolved_root = root.resolve()
    if not path.is_relative_to(resolved_root):
        return None
    parts = path.relative_to(resolved_root).parts
    return resolved_root / parts[0] / parts[1] if len(parts) >= 2 else None


def _overlaps(left: Path, right: Path) -> bool:
    return left.is_relative_to(right) or right.is_relative_to(left)


def _dependents(root: Path, target: Path) -> list[str]:
    """Runs still running or complete whose declared dependencies overlap `target`."""
    target = target.resolve()
    found = []
    for task_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for run_dir in sorted(path for path in task_dir.iterdir() if path.is_dir()):
            if run_dir.resolve() == target:
                continue
            try:
                record = read_run(run_dir)
            except ScratchRunError:
                continue
            if record["state"] in {"running", "complete"} and any(_overlaps(Path(path), target) for path in record.get("depends_on", [])):
                found.append(f"{record['task']}/{record['run']}")
    return found


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

    `depends_on` lists absolute paths outside the run that it reads (for example an earlier
    phase's output left in place, or a file inside another scratch run). While this run is
    running or complete, `clean` keeps every scratch run they fall in. They are recorded,
    not copied.
    """
    if not purpose.strip() or not owner.strip():
        raise ScratchRunError("a scratch run needs a purpose and an owner (session or agent name)")
    raw = [Path(path) for path in depends_on]
    if any(not path.is_absolute() for path in raw):
        raise ScratchRunError(f"depends_on needs absolute paths, got {[str(path) for path in raw]!r}")
    root = scratch_root() if root is None else checked_path(root)
    repo_root = REPO_ROOT if repo_root is None else repo_root
    dependencies = [str(checked_path(path).resolve()) for path in raw]
    resolved_root = root.resolve()
    for dependency in map(Path, dependencies):
        # A dependency covering the scratch root or a whole task directory has no single
        # run whose deps lock could guard it against a concurrent clean; name a run or a
        # path inside one instead.
        if resolved_root.is_relative_to(dependency) or (dependency.is_relative_to(resolved_root) and _owning_run(root, dependency) is None):
            raise ScratchRunError(f"depends_on must name one scratch run or a path inside it, not a directory above runs: {dependency}")
    directory = _run_dir(root, task, run)
    directory.parent.mkdir(exist_ok=True)
    try:
        directory.mkdir()
    except FileExistsError as error:
        raise ScratchRunError(f"scratch run already exists, resume it with open_run: {directory}") from error
    handle = _lock(directory)
    # Hold each depended-on run's deps lock until the label is written, so a concurrent
    # `_delete` either sees this dependency or has finished before it is registered.
    dep_locks: list[IO[bytes]] = []
    try:
        for target in sorted({holder for path in dependencies if (holder := _owning_run(root, Path(path))) is not None}):
            if target == directory.resolve():
                continue
            if not (target / RUN_FILE).is_file():
                raise ScratchRunError(f"depended-on scratch run {target} does not exist")
            dep_locks.append(_lock(target, DEPS_LOCK_FILE))
            if not (target / RUN_FILE).is_file():
                raise ScratchRunError(f"depended-on scratch run {target} was just deleted")
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
    except BaseException:
        _unlock(handle)
        shutil.rmtree(directory, ignore_errors=True)
        raise
    finally:
        for lock in dep_locks:
            _unlock(lock)
    LOGGER.info("created scratch run %s/%s at %s (%d dependencies)", task, run, directory, len(dependencies))
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


def _status(directory: Path, now: datetime, repo_root: Path) -> RunStatus:
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
    if state in {"abandoned", "delivered"}:
        dependents = _dependents(directory.parent.parent, directory)
        if dependents:
            return RunStatus(task, run, directory, state, IN_USE, "still needed by " + ", ".join(dependents), updated)
    if state == "abandoned":
        return RunStatus(task, run, directory, state, DELETABLE, record.get("reason", ""), updated)
    if state == "delivered":
        results = record.get("results", [])
        lost = _unverified_results(results, repo_root, digests=False) if results else ["(none recorded)"]
        if lost:
            return RunStatus(task, run, directory, state, ASK_OWNER, f"delivered results cannot be verified: {lost}", updated)
        return RunStatus(task, run, directory, state, DELETABLE, "results delivered to " + ", ".join(str(result["path"]) for result in results), updated)
    try:
        age = now - datetime.fromisoformat(str(updated))
    except (TypeError, ValueError):
        return RunStatus(task, run, directory, state, ASK_OWNER, f"unreadable updated_at {updated!r}", updated, progress)
    if age > STALE_AFTER:
        return RunStatus(task, run, directory, state, ASK_OWNER, f"untouched for {age.days} days", updated, progress)
    if state == "complete":
        return RunStatus(task, run, directory, state, AWAITING_DELIVERY, "finished; move the final results, then mark delivered", updated)
    return RunStatus(task, run, directory, state, PAUSED, "no process holds it; resume with open_run", updated, progress)


def survey(root: Path | None = None, *, now: datetime | None = None, repo_root: Path | None = None) -> list[RunStatus]:
    """Classify every directory under the scratch root; anything unexpected is for the owner.

    `repo_root` is any checkout of this repository; delivered repository results are looked
    up on its DEFAULT_BRANCH, so the worktree that delivered them may already be gone.
    """
    root = scratch_root() if root is None else checked_path(root)
    repo_root = REPO_ROOT if repo_root is None else repo_root
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
            statuses.append(_status(run_dir, now, repo_root))
    return statuses


def _delete(directory: Path, repo_root: Path) -> None:
    """Remove one run while holding its writer and deps locks, after re-checking under them
    that it is finished, no unfinished run depends on it and, if delivered, that every
    result still verifies with digests. Refuses any link or junction inside it."""
    handle = _lock(directory)
    try:
        deps = _lock(directory, DEPS_LOCK_FILE)
    except ScratchRunError:
        _unlock(handle)
        raise
    try:
        record = read_run(directory)
        if record["state"] not in {"delivered", "abandoned"}:
            raise ScratchRunError(f"{directory} changed state; not deleting")
        dependents = _dependents(directory.parent.parent, directory)
        if dependents:
            raise ScratchRunError(f"{directory} is still needed by {dependents}; not deleting")
        if record["state"] == "delivered":
            lost = _unverified_results(record.get("results", []), repo_root, digests=True)
            if lost or not record.get("results"):
                raise ScratchRunError(f"{directory}: delivered results cannot be verified {lost}; not deleting")
        check_tree(checked_path(directory))
        for child in directory.iterdir():
            if child.name in {LOCK_FILE, DEPS_LOCK_FILE}:
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    finally:
        _unlock(deps)
        _unlock(handle)
    (directory / LOCK_FILE).unlink(missing_ok=True)
    (directory / DEPS_LOCK_FILE).unlink(missing_ok=True)
    directory.rmdir()
    try:
        directory.parent.rmdir()
    except OSError:
        pass  # other runs of the same task remain


def clean(root: Path | None = None, *, apply: bool = False, now: datetime | None = None, repo_root: Path | None = None) -> list[RunStatus]:
    """Return the deletable runs; delete them only with ``apply=True``."""
    repo_root = REPO_ROOT if repo_root is None else repo_root
    deletable = [status for status in survey(root, now=now, repo_root=repo_root) if status.verdict == DELETABLE]
    for status in deletable:
        if apply:
            _delete(status.path, repo_root)
            LOGGER.info("deleted scratch run %s/%s (%s)", status.task, status.run, status.state)
    return deletable

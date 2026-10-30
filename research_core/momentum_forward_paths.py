"""Where the momentum-only forward log lives, and the one-way move out of the primary checkout.

Owner decision 2026-10-24: ongoing study results live under the research-data root as
`tasks/<task-id>/`. The forward log's default root is therefore
`<shared data root>/tasks/20261021-momentum-only-doubling/forward-log`, resolved at call time.
It used to be an untracked directory in the primary checkout (the legacy root).

`migrate_legacy_forward_log` copies the legacy files one way and never touches the legacy
directory. Files are published through a temp sibling and a no-replace rename, so an
interrupted copy leaves no truncated file under its final name. A file that already exists in
the new root must agree with legacy: byte-identical, except append-only `*.jsonl` ledgers where
legacy must be a byte prefix of the new file (the new one may have grown). Anything else raises
`ForwardLogMigrationError`, and the caller must not record.

Lock files: every legacy `*.lock` must be lockable before anything is copied, which proves no
recorder still owns the legacy log. A v2 attempt's `owner.lock` is then copied like data: recovery
needs it to prove a released owner and close the attempt as interrupted. Only the top-level
coordination locks (`.attempts-v2-*.lock`), which v2 recreates on demand, are not copied.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import uuid
from pathlib import Path

from research_core.artifact_store import file_digest, publish_noreplace, release_os_lock, safe_path, try_os_lock
from research_core.producer_data import REPO_ROOT, primary_checkout
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
TASK_ID = "20261021-momentum-only-doubling"
_STAGING_PREFIX = ".migrating-"
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)


class ForwardLogMigrationError(RuntimeError):
    """The legacy and new forward logs disagree or the legacy tree is unsafe to copy."""


def default_forward_log_root() -> Path:
    """`<shared data root>/tasks/<task>/forward-log`, resolved at call time."""
    return shared_data_root() / "tasks" / TASK_ID / "forward-log"


def legacy_forward_log_root(repo_root: Path = REPO_ROOT) -> Path | None:
    """The old untracked directory in the primary checkout (handles linked worktrees)."""
    primary = primary_checkout(repo_root.resolve())
    return None if primary is None else primary / "tasks" / TASK_ID / "forward-log"


def _legacy_files(legacy: Path) -> list[Path]:
    """Regular files under legacy, sorted by relative path; any link or special entry is an error."""
    found: list[Path] = []
    for directory, names, files in os.walk(legacy, followlinks=False):
        names.sort()
        for entry in [*names, *files]:
            path = Path(directory) / entry
            info = path.lstat()
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & _REPARSE:
                raise ForwardLogMigrationError(f"legacy forward log contains a link: {path}")
        for name in sorted(files):
            path = Path(directory) / name
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ForwardLogMigrationError(f"legacy forward log contains a non-regular file: {path}")
            if not (Path(directory) == legacy and name.endswith(".lock")):
                found.append(path)
    return sorted(found, key=lambda path: path.relative_to(legacy).as_posix())


def _is_prefix(prefix: Path, whole: Path) -> bool:
    size = prefix.stat().st_size
    if whole.stat().st_size < size:
        return False
    digest = hashlib.sha256()
    remaining = size
    with whole.open("rb") as stream:
        while remaining:
            chunk = stream.read(min(remaining, 1024 * 1024))
            if not chunk:
                return False
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest() == file_digest(prefix)


def _copy_noreplace(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(f"{_STAGING_PREFIX}{uuid.uuid4().hex}-{destination.name}")
    expected = file_digest(source)
    with source.open("rb") as incoming, staged.open("xb") as outgoing:
        shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if file_digest(staged) != expected or file_digest(source) != expected:
        staged.unlink()
        raise ForwardLogMigrationError(f"legacy file changed or copy mismatch: {source}")
    publish_noreplace(staged, destination)


def _assert_no_live_owner(legacy: Path) -> None:
    """Every legacy lock file must be lockable now: a held one means a recorder still owns the log."""
    for lock in sorted(legacy.rglob("*.lock")):
        with lock.open("r+b") as handle:
            if not try_os_lock(handle):
                raise ForwardLogMigrationError(f"legacy forward log is still in use (lock held: {lock}); migrate after that recorder stops")
            release_os_lock(handle)


def migrate_legacy_forward_log(legacy: Path | None, root: Path) -> tuple[int, int]:
    """Copy legacy files missing from `root`; return (copied, already_present). Legacy is never modified."""
    if legacy is None or not legacy.exists():
        return 0, 0
    legacy, root = safe_path(legacy), safe_path(root)
    if not legacy.is_dir():
        raise ForwardLogMigrationError(f"legacy forward log is not a directory: {legacy}")
    pending: list[tuple[Path, Path]] = []
    present = 0
    sources = _legacy_files(legacy)
    _assert_no_live_owner(legacy)
    for source in sources:  # validate everything before copying anything
        relative = source.relative_to(legacy)
        destination = safe_path(root / relative)
        if not destination.exists():
            pending.append((source, destination))
            continue
        if not destination.is_file():
            raise ForwardLogMigrationError(f"forward-log migration: not a regular file in new root: {destination}")
        agrees = _is_prefix(source, destination) if source.suffix == ".jsonl" else file_digest(source) == file_digest(destination)
        if not agrees:
            raise ForwardLogMigrationError(f"forward-log migration: {relative.as_posix()} differs between legacy {legacy} and new root {root}")
        present += 1
    for source, destination in pending:
        _copy_noreplace(source, destination)
    copied = len(pending)
    LOGGER.info("forward-log migration: copied %d, already present %d, legacy=%s, root=%s", copied, present, legacy, root)
    return copied, present


def resolve_forward_log_root(explicit: Path | None) -> Path:
    """The root to use. An explicit `--root` is returned as is, with no migration; the default migrates first."""
    if explicit is not None:
        return explicit
    root = default_forward_log_root()
    migrate_legacy_forward_log(legacy_forward_log_root(), root)
    return root

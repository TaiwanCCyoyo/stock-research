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

Coordination: every legacy `*.lock` is locked and held until the migration ends (a lock that
cannot be taken aborts it, nothing is copied), and a `.migration.lock` in the new root serializes
migrations. A held lock cannot be read through another handle on Windows, so its bytes are read
through the held handle. Old v1 code takes no lock, so a late writer is detected instead: the
legacy tree is snapshotted (path, size, sha256) before and after the copy and any difference
aborts with `ForwardLogMigrationError`. Listing and stat errors also fail closed.

A v2 attempt's `owner.lock` is copied like data: recovery needs it to prove a released owner and
close the attempt as interrupted. Only the top-level coordination locks (`.attempts-v2-*.lock`),
which v2 recreates on demand, are not copied.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import stat
import uuid
from contextlib import ExitStack
from pathlib import Path
from typing import IO

from research_core.artifact_store import file_digest, publish_noreplace, release_os_lock, safe_path, try_os_lock
from research_core.producer_data import REPO_ROOT, primary_checkout
from research_core.shared_data import shared_data_root

LOGGER = logging.getLogger(__name__)
TASK_ID = "20261021-momentum-only-doubling"
MIGRATION_LOCK = ".migration.lock"
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
    """Regular files under legacy, sorted by relative path.

    Any link, special entry, or listing/stat error is a `ForwardLogMigrationError`: an unreadable
    directory must never be skipped, or an incomplete copy would report success.
    """
    found: list[Path] = []
    pending = [legacy]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
            for entry in entries:
                path = Path(entry.path)
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & _REPARSE:
                    raise ForwardLogMigrationError(f"legacy forward log contains a link: {path}")
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    found.append(path)
                else:
                    raise ForwardLogMigrationError(f"legacy forward log contains a non-regular file: {path}")
        except OSError as error:
            raise ForwardLogMigrationError(f"cannot list legacy forward log {directory}: {error}") from error
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


def _read_held(handle: IO[bytes]) -> bytes:
    handle.seek(0)
    return handle.read()


def _copy_noreplace(source: Path, destination: Path, held: IO[bytes] | None = None) -> None:
    """Verified no-replace copy. A lock file we hold is read through that handle (Windows blocks others)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    staged = destination.with_name(f"{_STAGING_PREFIX}{uuid.uuid4().hex}-{destination.name}")
    if held is not None:
        data = _read_held(held)
        expected = hashlib.sha256(data).hexdigest()
        with staged.open("xb") as outgoing:
            outgoing.write(data)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if file_digest(staged) != expected:
            staged.unlink()
            raise ForwardLogMigrationError(f"copy mismatch: {source}")
    else:
        expected = file_digest(source)
        with source.open("rb") as incoming, staged.open("xb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            outgoing.flush()
            os.fsync(outgoing.fileno())
        if file_digest(staged) != expected or file_digest(source) != expected:
            staged.unlink()
            raise ForwardLogMigrationError(f"legacy file changed or copy mismatch: {source}")
    publish_noreplace(staged, destination)


def _hold_lock(path: Path, stack: ExitStack, busy: str) -> IO[bytes]:
    """Open `path` and keep its OS lock until `stack` closes; a lock that cannot be taken is an error."""
    try:
        handle = path.open("a+b")
    except OSError as error:
        raise ForwardLogMigrationError(f"cannot open lock file {path}: {error}") from error
    stack.callback(handle.close)
    if not try_os_lock(handle):
        raise ForwardLogMigrationError(f"{busy} (lock held: {path})")
    stack.callback(release_os_lock, handle)
    return handle


def _snapshot_legacy(legacy: Path, files: list[Path]) -> dict[str, tuple[int, str]]:
    """(size, sha256) per file; lock files carry their size only (their locked byte is unreadable)."""
    result: dict[str, tuple[int, str]] = {}
    for path in files:
        digest = "lock" if path.name.endswith(".lock") else file_digest(path)
        result[path.relative_to(legacy).as_posix()] = (path.stat().st_size, digest)
    return result


def _migrate(legacy: Path, root: Path) -> tuple[int, int]:
    with ExitStack() as stack:
        files = _legacy_files(legacy)
        held: dict[Path, IO[bytes]] = {}
        for path in files:
            if path.name.endswith(".lock"):
                held[path] = _hold_lock(path, stack, "legacy forward log is still in use; migrate after that recorder stops")
        held_digest = {path: hashlib.sha256(_read_held(handle)).hexdigest() for path, handle in held.items()}
        root.mkdir(parents=True, exist_ok=True)
        _hold_lock(root / MIGRATION_LOCK, stack, "another forward-log migration is running")
        before = _snapshot_legacy(legacy, files)
        pending: list[tuple[Path, Path]] = []
        present = 0
        for source in files:  # validate everything before copying anything
            if source.name.endswith(".lock") and source.parent == legacy:
                continue  # top-level coordination locks are recreated on demand
            relative = source.relative_to(legacy)
            destination = safe_path(root / relative)
            if not destination.exists():
                pending.append((source, destination))
                continue
            if not destination.is_file():
                raise ForwardLogMigrationError(f"forward-log migration: not a regular file in new root: {destination}")
            if source in held:
                agrees = held_digest[source] == file_digest(destination)
            elif source.suffix == ".jsonl":
                agrees = _is_prefix(source, destination)
            else:
                agrees = file_digest(source) == file_digest(destination)
            if not agrees:
                raise ForwardLogMigrationError(f"forward-log migration: {relative.as_posix()} differs between legacy {legacy} and new root {root}")
            present += 1
        for source, destination in pending:
            _copy_noreplace(source, destination, held.get(source))
        after = _snapshot_legacy(legacy, _legacy_files(legacy))
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        if changed:
            raise ForwardLogMigrationError(
                f"late writer detected: legacy forward log changed during migration ({', '.join(changed[:10])}); stop the old recorder and rerun"
            )
    return len(pending), present


def migrate_legacy_forward_log(legacy: Path | None, root: Path) -> tuple[int, int]:
    """Copy legacy files missing from `root`; return (copied, already_present). Legacy is never modified."""
    if legacy is None or not legacy.exists():
        return 0, 0
    legacy, root = safe_path(legacy), safe_path(root)
    if not legacy.is_dir():
        raise ForwardLogMigrationError(f"legacy forward log is not a directory: {legacy}")
    try:
        copied, present = _migrate(legacy, root)
    except OSError as error:
        raise ForwardLogMigrationError(f"forward-log migration failed: {error}") from error
    LOGGER.info("forward-log migration: copied %d, already present %d, legacy=%s, root=%s", copied, present, legacy, root)
    return copied, present


def resolve_forward_log_root(explicit: Path | None) -> Path:
    """The root to use. An explicit `--root` is returned as is, with no migration; the default migrates first."""
    if explicit is not None:
        return explicit
    root = default_forward_log_root()
    migrate_legacy_forward_log(legacy_forward_log_root(), root)
    return root

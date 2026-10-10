"""Shared output helper for this task's one-time writers."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("archive_io")


def _committed_marker(bak: Path) -> Path:
    return bak.with_name(bak.name + ".committed")


def _discard_backup(bak: Path) -> bool:
    """Post-commit cleanup: mark the backup as superseded, then delete it. Returns False when it could
    not be deleted (for example a Windows lock); the marker then lets the next run finish the job."""
    try:
        _committed_marker(bak).write_bytes(b"")
        bak.unlink()
        _committed_marker(bak).unlink()
        return True
    except OSError as exc:
        log.warning("new outputs are in place, but %s could not be removed yet (%s); the next run retries", bak, exc)
        return False


def swap_in(outputs: dict[Path, bytes]) -> list[Path]:
    """Replace every target together: stage new bytes, move the old files aside, then move the new
    ones in. Any failure before the new files are in place puts every old file back, so the targets are
    never left half-updated. Removing the old copies afterwards is cleanup, not part of the swap: if it
    fails the swap still succeeded, and the backups it could not remove are returned."""
    for t in outputs:  # finish an earlier run's cleanup, which is safe only when marked as committed
        bak = t.with_name(t.name + ".previous")
        if bak.exists() and _committed_marker(bak).exists():
            _discard_backup(bak)
        elif _committed_marker(bak).exists():
            _committed_marker(bak).unlink()
    leftovers = [str(x) for t in outputs for x in (t.with_name(t.name + ".partial"), t.with_name(t.name + ".previous")) if x.exists()]
    if leftovers:  # an earlier run was interrupted mid-swap; never guess which copy is right
        raise SystemExit(f"leftover files from an interrupted run, resolve them by hand first: {leftovers}")
    staged: dict[Path, Path] = {}
    backups: dict[Path, Path] = {}
    placed: list[Path] = []
    try:
        for target, data in outputs.items():
            tmp = target.with_name(target.name + ".partial")
            staged[target] = tmp  # registered first, so a failed or partial write is cleaned up too
            tmp.write_bytes(data)
        for target in staged:
            if target.exists():
                bak = target.with_name(target.name + ".previous")
                os.replace(target, bak)
                backups[target] = bak  # registered only once the old file is really there
        for target, tmp in staged.items():
            os.replace(tmp, target)
            placed.append(target)
    except BaseException:
        for target in placed:
            target.unlink(missing_ok=True)
        for target, bak in backups.items():
            os.replace(bak, target)
        for tmp in staged.values():
            tmp.unlink(missing_ok=True)
        log.error("swap failed; previous outputs restored")
        raise
    return [bak for bak in backups.values() if not _discard_backup(bak)]

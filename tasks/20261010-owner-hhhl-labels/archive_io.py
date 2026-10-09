"""Shared output helper for this task's one-time writers."""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("archive_io")


def swap_in(outputs: dict[Path, bytes]) -> None:
    """Replace every target together: stage new bytes, move the old files aside, then move the new
    ones in. Any failure puts every old file back, so the targets are never left half-updated."""
    leftovers = [str(x) for t in outputs for x in (t.with_name(t.name + ".partial"), t.with_name(t.name + ".previous")) if x.exists()]
    if leftovers:  # an earlier run was interrupted; never guess which copy is right
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
    for bak in backups.values():
        bak.unlink()

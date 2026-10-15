"""Resolve stock-research's shared data root, which lives outside every checkout.

Owner decision 2026-10-15 (docs/en/decision-records/2026-10-15-maintained-shared-data.md):
reusable research data that is kept current lives in one directory outside the
repository, so no worktree copies it and no Git operation can remove it. The root comes
from, in order:

1. ``STOCK_RESEARCH_SHARED_ROOT`` in the process environment;
2. the same key in the primary checkout's ignored ``.env.local``, found through
   ``git rev-parse --git-common-dir`` so linked worktrees need no copy of it.

There is no fallback. A root inside the primary checkout or any of its worktrees is
refused, as is one that is or sits under a link, junction or hardlink: either is
exactly the per-checkout exposure this root exists to avoid.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

from research_core.producer_data import ENV_FILE_NAME, REPO_ROOT, primary_checkout, read_env_file_value
from research_core.research_data_paths import checked_path

ENV_KEY = "STOCK_RESEARCH_SHARED_ROOT"


class SharedRootError(ValueError):
    """The shared data root is not configured or not usable; there is no fallback."""


def _worktrees(primary: Path) -> list[Path]:
    """Every checkout registered with primary's Git object store, primary included."""
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    result = subprocess.run(
        ["git", "-c", "core.quotePath=false", "-C", str(primary), "worktree", "list", "--porcelain", "-z"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=environment,
        timeout=30,
    )
    if result.returncode != 0:
        raise SharedRootError(f"cannot list worktrees of {primary}: {result.stderr.strip()}")
    return [Path(field.removeprefix("worktree ")).resolve() for field in result.stdout.split("\0") if field.startswith("worktree ")]


def _validated(value: str, source: str, primary: Path | None) -> Path:
    root = Path(value.strip())
    if not value.strip() or not root.is_absolute():
        raise SharedRootError(f"{ENV_KEY} from {source} must be an absolute directory path, got {value!r}")
    try:
        # Before resolve(): a link inside a checkout pointing outside must not pass as "outside".
        checked = checked_path(root)
    except ValueError as error:
        raise SharedRootError(f"{ENV_KEY} from {source} must not be or sit under a link, junction or hardlink: {error}") from error
    if not checked.is_dir():
        raise SharedRootError(f"{ENV_KEY} directory from {source} is unavailable: {root}; create it or fix the setting, no automatic fallback")
    resolved = checked.resolve()
    if primary is not None:
        for checkout in [primary.resolve(), *_worktrees(primary)]:
            if resolved.is_relative_to(checkout) or checkout.is_relative_to(resolved):
                raise SharedRootError(f"{ENV_KEY} from {source} must be outside every checkout and worktree; it overlaps {checkout}: {resolved}")
    return resolved


def shared_data_root(*, environ: Mapping[str, str] | None = None, repo_root: Path | None = None) -> Path:
    environ = os.environ if environ is None else environ
    repo_root = REPO_ROOT if repo_root is None else repo_root
    primary = primary_checkout(repo_root.resolve())
    configured = environ.get(ENV_KEY)
    if configured is not None:
        return _validated(configured, "the process environment", primary)
    env_file = primary / ENV_FILE_NAME if primary is not None else None
    if env_file is not None:
        try:
            value = read_env_file_value(env_file, ENV_KEY)
        except ValueError as error:
            raise SharedRootError(str(error)) from error
        if value is not None:
            return _validated(value, str(env_file), primary)
    checked = str(env_file) if env_file is not None else "<no primary checkout found through git>"
    raise SharedRootError(f"{ENV_KEY} is not configured: not in the process environment and not in {checked}; no automatic fallback")

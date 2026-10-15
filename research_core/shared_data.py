"""Resolve stock-research's shared data root, which lives outside every checkout.

Owner decision 2026-10-15 (docs/en/decision-records/2026-10-15-maintained-shared-data.md):
reusable research data that is kept current lives in one directory outside the
repository, so no worktree copies it and no Git operation can remove it. The root comes
from, in order:

1. ``STOCK_RESEARCH_SHARED_ROOT`` in the process environment;
2. the same key in the primary checkout's ignored ``.env.local``, found through
   ``git rev-parse --git-common-dir`` so linked worktrees need no copy of it.

There is no fallback. A root inside the primary checkout or any of its worktrees is
refused, because that is exactly the per-checkout copy this root exists to avoid.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from research_core.producer_data import ENV_FILE_NAME, REPO_ROOT, primary_checkout, read_env_file_value

ENV_KEY = "STOCK_RESEARCH_SHARED_ROOT"


class SharedRootError(ValueError):
    """The shared data root is not configured or not usable; there is no fallback."""


def _validated(value: str, source: str, primary: Path | None) -> Path:
    root = Path(value.strip())
    if not value.strip() or not root.is_absolute():
        raise SharedRootError(f"{ENV_KEY} from {source} must be an absolute directory path, got {value!r}")
    if not root.is_dir():
        raise SharedRootError(f"{ENV_KEY} directory from {source} is unavailable: {root}; create it or fix the setting, no automatic fallback")
    resolved = root.resolve()
    if primary is not None and resolved.is_relative_to(primary.resolve()):
        raise SharedRootError(f"{ENV_KEY} from {source} must be outside the checkout {primary}: {resolved}")
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

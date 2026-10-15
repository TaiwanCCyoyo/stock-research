"""Resolve the local producer input root without acquiring or replacing data.

The producer's live data lives outside every checkout (owner decision
2026-10-15, docs/en/producer-layout-migration.md). The root comes from, in order:

1. ``STOCK_PRODUCER_DATA_ROOT`` in the process environment;
2. the same key in the primary checkout's ignored ``.env.local``, found through
   ``git rev-parse --git-common-dir`` so linked worktrees need no copy of it.

Nothing falls back to ``<checkout>/stock-data-downloader/data``: after the move
that directory holds only tracked producer config, and a silent fallback would
return no files instead of an error.
"""

from __future__ import annotations

import functools
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

ENV_KEY = "STOCK_PRODUCER_DATA_ROOT"
ENV_FILE_NAME = ".env.local"
# Every live producer root carries this artifact; a code-only directory does not.
SENTINEL = "price_daily.parquet"
# Variables that would make git describe some other repository than repo_root.
_GIT_LOCATION_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")


class ProducerRootError(ValueError):
    """The producer data root is not configured or not usable; there is no fallback."""


@functools.cache
def primary_checkout(repo_root: Path) -> Path | None:
    """Return the primary checkout that owns repo_root's Git object store, if any."""
    environment = {key: value for key, value in os.environ.items() if key not in _GIT_LOCATION_VARIABLES}
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    common = Path(result.stdout.strip())
    return common.parent if common.name == ".git" else None


def read_env_file_value(path: Path, key: str = ENV_KEY) -> str | None:
    """Return key's value from path, None when absent; parse no other key."""
    if not path.is_file():
        return None
    found: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        stripped = line.strip()
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        name, separator, value = stripped.partition("=")
        if name.strip() != key:
            continue
        if not separator:
            raise ProducerRootError(f"{key} in {path} has no value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        found.append(value)
    if len(found) > 1:
        raise ProducerRootError(f"{key} is set {len(found)} times in {path}")
    return found[0] if found else None


def _validated(value: str, source: str) -> Path:
    root = Path(value.strip())
    if not value.strip() or not root.is_absolute():
        raise ProducerRootError(f"{ENV_KEY} from {source} must be an absolute directory path, got {value!r}")
    if not root.is_dir():
        raise ProducerRootError(f"{ENV_KEY} directory from {source} is unavailable: {root}; no automatic fallback")
    if not (root / SENTINEL).is_file():
        raise ProducerRootError(f"{ENV_KEY} directory from {source} has no {SENTINEL}: {root}; it is not a producer data root")
    return root.resolve()


def producer_data_root(*, environ: Mapping[str, str] | None = None, repo_root: Path | None = None) -> Path:
    environ = os.environ if environ is None else environ
    repo_root = REPO_ROOT if repo_root is None else repo_root

    configured = environ.get(ENV_KEY)
    if configured is not None:
        return _validated(configured, "the process environment")

    primary = primary_checkout(repo_root.resolve())
    env_file = primary / ENV_FILE_NAME if primary is not None else None
    if primary is not None and primary.resolve() != repo_root.resolve():
        # Legacy only: a linked worktree seeded before 2026-10-15 may hold a frozen
        # input snapshot under a running study. Switching it silently to live data
        # would change that study's inputs. Dead once those worktrees are retired.
        snapshot = repo_root / "stock-data-downloader" / "data"
        if (snapshot / SENTINEL).is_file():
            raise ProducerRootError(
                f"{repo_root} holds its own seeded producer snapshot at {snapshot}; this is never chosen automatically. "
                f"Set {ENV_KEY} or pass --data-path either to that snapshot (keep the frozen inputs) "
                f"or to the live root configured in {env_file} (adopt live read-only inputs)"
            )
    if env_file is not None:
        value = read_env_file_value(env_file)
        if value is not None:
            return _validated(value, str(env_file))

    checked = str(env_file) if env_file is not None else "<no primary checkout found through git>"
    raise ProducerRootError(f"{ENV_KEY} is not configured: not in the process environment and not in {checked}; no automatic fallback")

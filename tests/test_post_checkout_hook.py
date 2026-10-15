"""Regression test: a new linked worktree gets no producer submodule and no data copy.

`.githooks/post-checkout` used to initialize the stock-data-downloader submodule and copy
about 5 GB of producer inputs into every new worktree. Research now reads sealed
producer-input versions in place by pin (`research_core/producer_inputs.py`), so the hook
is retired. This runs real `git worktree add` with the repository's own hooks directory,
because a hook that silently came back would only show up as a full disk.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[1] / ".githooks"
# file:// submodule URLs are blocked by default (CVE-2022-39253); the double is local.
_ALLOW_FILE_PROTOCOL_ENV = {**os.environ, "GIT_ALLOW_PROTOCOL": "file"}


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-c", "commit.gpgSign=false", *args], cwd=cwd, capture_output=True, text=True, check=True, env=_ALLOW_FILE_PROTOCOL_ENV)


def _is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))


@pytest.fixture()
def main_repo_with_submodule(tmp_path: Path) -> Path:
    """A primary checkout shaped like this one: producer submodule plus ignored live data."""
    producer = tmp_path / "producer"
    producer.mkdir()
    _git(["init", "-q"], producer)
    (producer / "data").mkdir()
    (producer / "data" / "stock_category.json5").write_text("{}\n", encoding="utf-8")
    _git(["add", "data/stock_category.json5"], producer)
    _git(["-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-q", "-m", "init"], producer)

    repo = tmp_path / "main"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["submodule", "add", str(producer), "stock-data-downloader"], repo)
    _git(["-c", "user.email=test@example.com", "-c", "user.name=Test", "commit", "-q", "-m", "add submodule"], repo)
    data = repo / "stock-data-downloader" / "data"
    (data / "price_daily.parquet").write_text("live parquet stand-in\n", encoding="utf-8")
    (data / "2330_day.csv").write_text("live daily bars\n", encoding="utf-8")
    _git(["config", "core.hooksPath", str(HOOKS_DIR)], repo)
    return repo


def test_no_checkout_hook_seeds_worktrees() -> None:
    assert not (HOOKS_DIR / "post-checkout").exists()
    for hook in HOOKS_DIR.iterdir():
        text = hook.read_text(encoding="utf-8")
        assert "seed_worktree_inputs" not in text and "submodule update" not in text, hook


def test_new_worktree_has_no_submodule_checkout_and_no_data_copy(main_repo_with_submodule: Path, tmp_path: Path) -> None:
    main_data = main_repo_with_submodule / "stock-data-downloader" / "data"
    before = {path: path.read_bytes() for path in main_data.rglob("*") if path.is_file()}
    worktree = tmp_path / "research worktree"

    _git(["worktree", "add", "-q", "-b", "research", str(worktree)], main_repo_with_submodule)

    status = _git(["submodule", "status"], worktree).stdout
    assert status.startswith("-"), status  # registered but not initialized
    producer = worktree / "stock-data-downloader"
    assert not producer.exists() or not any(producer.iterdir())
    assert not (worktree / ".tmp").exists()
    assert all(not _is_link(path) for path in worktree.rglob("*") if ".git" not in path.parts)
    assert {path: path.read_bytes() for path in main_data.rglob("*") if path.is_file()} == before

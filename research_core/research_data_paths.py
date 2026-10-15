"""Validate explicit shared data roots without copying or linking their files."""

from __future__ import annotations

import logging
import os
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from research_core.artifact_store import relative_name, safe_path

LOGGER = logging.getLogger(__name__)
DATA_ROOT_ENV = "STOCK_RESEARCH_DATA_ROOT"
# Win32 also reserves superscript 1, 2 and 3 in COM/LPT device names.
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"{prefix}{digit}" for prefix in ("COM", "LPT") for digit in (*"123456789", *"¹²³"))}


def _artifact_name(name: str) -> str:
    validated = relative_name(name)
    for component in validated.split("/"):
        if (
            component.endswith((".", " "))
            or any(character in '<>"|?*' or ord(character) < 32 or 127 <= ord(character) <= 159 for character in component)
            or component.split(".")[0].upper() in WINDOWS_DEVICES
        ):
            raise ValueError(f"unsafe Windows artifact name: {name}")
    return validated


def _reject_alias(path: Path, info: os.stat_result) -> None:
    """The one predicate for a forbidden filesystem alias: link, reparse point or hardlink."""
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
        raise ValueError(f"linked/reparse path forbidden: {path}")
    if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
        raise ValueError(f"hardlinked file forbidden: {path}")


def _checked_path(path: Path) -> Path:
    """Check lexical ancestors, including dangling reparse points and hardlinks."""
    absolute = safe_path(path)
    for ancestor in (absolute, *absolute.parents):
        try:
            info = ancestor.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        _reject_alias(ancestor, info)
    return absolute


checked_path = _checked_path
"""Public name for the alias check: no link, reparse point or hardlink on the path or its ancestors."""


def _check_tree(root: Path) -> int:
    """Apply `_reject_alias` to every entry below `root`; return how many were checked.

    `root` and its own ancestors must already have passed `_checked_path`. Each entry gets
    one lstat and a directory is entered only after it passed, so when an entry is reached
    every directory between it and `root` has already been checked. That is the predicate
    `_checked_path` applies per entry, at a cost linear in the entry count instead of
    entries times path depth. It is a point-in-time check, as the per-entry form was.
    """
    checked = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            names = [entry.name for entry in entries]
        for name in names:
            child = directory / name
            try:
                info = child.lstat()
            except (FileNotFoundError, NotADirectoryError):
                continue
            _reject_alias(child, info)
            checked += 1
            if stat.S_ISDIR(info.st_mode):
                pending.append(child)
    return checked


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _git_read(root: Path, *arguments: str) -> str:
    command = ["git", "-c", "core.quotePath=false", "-C", str(root), *arguments]
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    except (OSError, UnicodeError) as error:
        LOGGER.warning("Git identity check could not run: root=%s error=%s", root, error)
        raise ValueError(f"Git worktree identity check failed: {error}") from error
    if result.returncode != 0:
        message = f"stderr={result.stderr.strip()!r}; stdout={result.stdout.strip()!r}"
        LOGGER.warning("Git identity check failed: root=%s code=%s message=%s", root, result.returncode, message)
        raise ValueError(f"Git worktree identity check failed (exit code {result.returncode}): {message}")
    return result.stdout


@dataclass(frozen=True)
class DataRoots:
    """Primary checkout and its explicitly configured shared research_data root."""

    primary: Path
    data: Path

    def __post_init__(self) -> None:
        if not self.primary.is_absolute() or not self.data.is_absolute():
            raise ValueError("primary and data roots must be explicit absolute paths")
        primary = _checked_path(self.primary)
        data = _checked_path(self.data)
        if data.name != "research_data":
            raise ValueError("data root must be named research_data")
        if any(part.casefold() in {".worktrees", ".tmp"} for part in data.parts):
            raise ValueError("data root cannot be under .worktrees or .tmp")
        if data.parent != primary:
            raise ValueError("data root must be directly under its primary checkout")
        git_directory = _checked_path(primary / ".git")
        if not git_directory.is_dir():
            raise ValueError("data root must belong to a primary checkout with a .git directory")
        if data.exists() and not data.is_dir():
            raise ValueError("data root must be a directory")
        object.__setattr__(self, "primary", primary)
        object.__setattr__(self, "data", data)
        LOGGER.debug("Validated research data roots: primary=%s data=%s", primary, data)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None, *, worktree: Path | None = None) -> DataRoots:
        environment = os.environ if env is None else env
        value = environment.get(DATA_ROOT_ENV)
        if not value or not Path(value).is_absolute():
            raise ValueError(f"{DATA_ROOT_ENV} must be an explicit absolute path")
        data = Path(value)
        roots = cls(primary=data.parent, data=data)
        if worktree is not None:
            checked_worktree = _checked_path(worktree)
            if _overlaps(data, checked_worktree):
                raise ValueError("data root overlaps worktree")
            roots.validate_worktree(checked_worktree)
        return roots

    def artifact_path(self, scope: str, name: str) -> Path:
        """Return a checked path; primary artifacts are limited to owned stores."""
        validated_name = _artifact_name(name)
        if scope == "data":
            root = self.data
        elif scope == "primary":
            if validated_name.split("/")[0] not in {"tasks", "research_cache"}:
                raise ValueError("primary artifacts must be under tasks/ or research_cache/")
            root = self.primary
        else:
            raise ValueError(f"unknown artifact scope: {scope}")
        path = _checked_path(root / validated_name)
        LOGGER.debug("Validated artifact path: scope=%s path=%s", scope, path)
        return path

    def validate_worktree(self, worktree: Path) -> None:
        """Reject shared-root copies and filesystem aliases anywhere in a worktree."""
        worktree = _checked_path(worktree)
        protected = (self.primary / ".git", self.primary / "research_cache", self.primary / "tasks", self.primary / "stock-data-downloader", self.data)
        for root in protected:
            if _overlaps(worktree, root):
                raise ValueError(f"worktree overlaps protected primary root: {root}")
        if not worktree.is_dir():
            raise ValueError("worktree must be an existing directory")
        copied_root = worktree / "research_data"
        if os.path.lexists(copied_root):
            raise ValueError("worktree must not contain research_data, including empty or linked roots")

        entries = _check_tree(worktree)
        git_file = _checked_path(worktree / ".git")
        if not git_file.is_file():
            raise ValueError("linked worktree must have a regular .git file")
        registered = {
            Path(field.removeprefix("worktree "))
            for field in _git_read(self.primary, "worktree", "list", "--porcelain", "-z").split("\0")
            if field.startswith("worktree ")
        }
        if worktree == self.primary or worktree not in registered:
            raise ValueError(f"worktree is not registered with primary checkout: {worktree}")
        common_dir = Path(_git_read(worktree, "rev-parse", "--path-format=absolute", "--git-common-dir").rstrip("\r\n"))
        top_level = Path(_git_read(worktree, "rev-parse", "--show-toplevel").rstrip("\r\n"))
        if common_dir != self.primary / ".git" or top_level != worktree:
            raise ValueError(f"Git worktree identity does not match primary checkout: {worktree}")
        admin = _checked_path(Path(_git_read(worktree, "rev-parse", "--absolute-git-dir").rstrip("\r\n")))
        if admin.parent != self.primary / ".git" / "worktrees":
            raise ValueError(f"Git metadata is not linked worktree administration: {admin}")
        try:
            back_pointer = Path(_checked_path(admin / "gitdir").read_text(encoding="utf-8").rstrip("\r\n"))
        except (OSError, UnicodeError) as error:
            raise ValueError(f"Git worktree back-pointer check failed: {error}") from error
        if back_pointer != git_file:
            raise ValueError(f"Git worktree administration belongs to another path: {admin}")
        LOGGER.debug("Validated worktree isolation: %s entries=%d", worktree, entries)

"""Validate explicit shared data roots without copying or linking their files."""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from research_core.artifact_store import relative_name, safe_path

LOGGER = logging.getLogger(__name__)
DATA_ROOT_ENV = "STOCK_RESEARCH_DATA_ROOT"
WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{number}" for number in range(1, 10)), *(f"LPT{number}" for number in range(1, 10))}


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


def _checked_path(path: Path) -> Path:
    """Check lexical ancestors, including dangling reparse points and hardlinks."""
    absolute = safe_path(path)
    for ancestor in (absolute, *absolute.parents):
        try:
            info = ancestor.lstat()
        except (FileNotFoundError, NotADirectoryError):
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            raise ValueError(f"linked/reparse path forbidden: {ancestor}")
        if stat.S_ISREG(info.st_mode) and info.st_nlink > 1:
            raise ValueError(f"hardlinked file forbidden: {ancestor}")
    return absolute


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


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
        if worktree == self.primary or _overlaps(worktree, self.data):
            raise ValueError("worktree must be separate from primary shared data")
        if not worktree.is_dir():
            raise ValueError("worktree must be an existing directory")
        copied_root = worktree / "research_data"
        if os.path.lexists(copied_root):
            raise ValueError("worktree must not contain research_data, including empty or linked roots")

        def walk_error(error: OSError) -> None:
            raise error

        for directory, directories, files in os.walk(worktree, followlinks=False, onerror=walk_error):
            _checked_path(Path(directory))
            for name in (*directories, *files):
                _checked_path(Path(directory) / name)
        LOGGER.debug("Validated worktree isolation: %s", worktree)

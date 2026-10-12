"""Synthetic checkout tests for shared paths and worktree isolation."""

import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, Path, Path]:
    primary = tmp_path / "primary"
    (primary / ".git").mkdir(parents=True)
    data = primary / "research_data"
    data.mkdir()
    worktree = primary / ".worktrees" / "task"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text("gitdir: ../../.git/worktrees/task", encoding="utf-8")
    return primary, data, worktree


def test_explicit_root_and_worktree_use_shared_paths(checkout: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    primary, data, worktree = checkout
    monkeypatch.setenv(DATA_ROOT_ENV, str(data))
    roots = DataRoots.from_env(worktree=worktree)
    assert roots.primary == primary
    assert roots.data == data
    assert roots.artifact_path("data", "patterns/v1/packet.json") == data / "patterns/v1/packet.json"
    assert roots.artifact_path("primary", "tasks/study/result.json") == primary / "tasks/study/result.json"
    assert roots.artifact_path("primary", "research_cache/prices/v1") == primary / "research_cache/prices/v1"
    assert not (worktree / "research_data").exists()


@pytest.mark.parametrize("value", [None, "", "research_data", "C:research_data", r"\research_data"])
def test_missing_or_relative_configuration_fails(value: str | None) -> None:
    env = {} if value is None else {DATA_ROOT_ENV: value}
    with pytest.raises(ValueError, match="explicit absolute"):
        DataRoots.from_env(env)


def test_direct_constructor_validates_primary_and_data(checkout: tuple[Path, Path, Path]) -> None:
    primary, data, _ = checkout
    assert DataRoots(primary, data).data == data
    with pytest.raises(ValueError, match="explicit absolute"):
        DataRoots(Path("relative"), data)
    with pytest.raises(ValueError, match="directly under"):
        DataRoots(primary.parent, data)
    with pytest.raises(ValueError, match="named research_data"):
        DataRoots(primary, primary / "other")


@pytest.mark.parametrize("forbidden", [".worktrees", ".tmp"])
def test_direct_constructor_rejects_forbidden_location(checkout: tuple[Path, Path, Path], forbidden: str) -> None:
    primary, _, _ = checkout
    nested = primary / forbidden / "fake-primary"
    (nested / ".git").mkdir(parents=True)
    with pytest.raises(ValueError, match="cannot be under"):
        DataRoots(nested, nested / "research_data")


def test_direct_constructor_rejects_git_file(checkout: tuple[Path, Path, Path]) -> None:
    primary, _, _ = checkout
    worktree = primary.parent / "separate-worktree"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../primary/.git/worktrees/task", encoding="utf-8")
    with pytest.raises(ValueError, match="primary checkout"):
        DataRoots(worktree, worktree / "research_data")


@pytest.mark.parametrize("location", ["other", ".worktrees/task/research_data", ".tmp/research_data", "nested/research_data"])
def test_root_must_belong_to_primary(checkout: tuple[Path, Path, Path], location: str) -> None:
    primary, _, _ = checkout
    with pytest.raises(ValueError):
        DataRoots.from_env({DATA_ROOT_ENV: str(primary / location)})


def test_worktree_git_file_cannot_be_primary(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: other", encoding="utf-8")
    with pytest.raises(ValueError, match="primary checkout"):
        DataRoots.from_env({DATA_ROOT_ENV: str(tmp_path / "research_data")})


def test_root_traversal_rejected_before_normalizing(checkout: tuple[Path, Path, Path]) -> None:
    primary, _, _ = checkout
    with pytest.raises(ValueError, match="traversal"):
        DataRoots.from_env({DATA_ROOT_ENV: str(primary / "nested" / ".." / "research_data")})


def test_data_file_cannot_be_root(checkout: tuple[Path, Path, Path]) -> None:
    _, data, _ = checkout
    data.rmdir()
    data.write_text("file", encoding="utf-8")
    with pytest.raises(ValueError, match="directory"):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)})


@pytest.mark.parametrize(
    "name",
    ["../escape", "a/../../escape", "/absolute", "C:/drive", "C:relative", "//server/share", r"\\server\share", "data:stream", "a\\b", "a//b", "./a", ""],
)
def test_artifact_names_reject_nonportable_or_escaping_paths(checkout: tuple[Path, Path, Path], name: str) -> None:
    _, data, _ = checkout
    roots = DataRoots.from_env({DATA_ROOT_ENV: str(data)})
    with pytest.raises(ValueError, match="unsafe artifact name"):
        roots.artifact_path("data", name)


@pytest.mark.parametrize(
    "component",
    [
        ".. ",
        "trailing.",
        "trailing ",
        "null\0byte",
        "tab\tbyte",
        "control\x7fbyte",
        "a<b",
        "a>b",
        'a"b',
        "a|b",
        "a?b",
        "a*b",
        "CON",
        "con.txt",
        "PRN",
        "AUX.bin",
        "NUL",
        "COM1",
        "com9.csv",
        "LPT1",
        "lpt9.json",
    ],
)
@pytest.mark.parametrize("scope,prefix", [("data", "nested"), ("primary", "tasks")])
def test_windows_special_components_rejected(checkout: tuple[Path, Path, Path], component: str, scope: str, prefix: str) -> None:
    primary, data, _ = checkout
    with pytest.raises(ValueError, match="unsafe Windows artifact name"):
        DataRoots(primary, data).artifact_path(scope, f"{prefix}/{component}/artifact.json")


@pytest.mark.parametrize("name", ["CONTEXT.txt", "COM10.txt", "LPT10.txt", "normal.data"])
def test_ordinary_device_prefix_names_allowed(checkout: tuple[Path, Path, Path], name: str) -> None:
    primary, data, _ = checkout
    assert DataRoots(primary, data).artifact_path("data", name) == data / name


@pytest.mark.parametrize("scope,name", [("primary", "scripts/a.py"), ("primary", "tasks-other/a"), ("unknown", "safe")])
def test_scopes_are_limited(checkout: tuple[Path, Path, Path], scope: str, name: str) -> None:
    _, data, _ = checkout
    with pytest.raises(ValueError):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)}).artifact_path(scope, name)


@pytest.mark.parametrize("target", ["primary", "data", "ancestor", "data_child"])
def test_worktree_overlap_rejected(checkout: tuple[Path, Path, Path], target: str) -> None:
    primary, data, _ = checkout
    path = {"primary": primary, "data": data, "ancestor": primary.parent, "data_child": data / "child"}[target]
    with pytest.raises(ValueError):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)}, worktree=path)


@pytest.mark.parametrize("populated", [False, True])
def test_local_copy_even_empty_is_rejected(checkout: tuple[Path, Path, Path], populated: bool) -> None:
    _, data, worktree = checkout
    local = worktree / "research_data"
    local.mkdir()
    if populated:
        (local / "data.bin").write_bytes(b"copied")
    with pytest.raises(ValueError, match="must not contain research_data"):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)}, worktree=worktree)


def test_missing_worktree_is_rejected(checkout: tuple[Path, Path, Path]) -> None:
    _, data, worktree = checkout
    with pytest.raises(ValueError, match="existing directory"):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)}, worktree=worktree / "missing")


@pytest.mark.parametrize("in_worktree", [False, True])
def test_hardlinked_file_rejected(checkout: tuple[Path, Path, Path], in_worktree: bool) -> None:
    _, data, worktree = checkout
    source = data / "source.bin"
    source.write_bytes(b"shared")
    alias = (worktree if in_worktree else data) / "alias.bin"
    os.link(source, alias)
    roots = DataRoots.from_env({DATA_ROOT_ENV: str(data)})
    with pytest.raises(ValueError, match="hardlinked"):
        if in_worktree:
            roots.validate_worktree(worktree)
        else:
            roots.artifact_path("data", "alias.bin/child")
    assert source.read_bytes() == b"shared"


def test_simulated_reparse_rejected_before_walking(checkout: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _, data, worktree = checkout
    reparse = worktree / "junction"
    reparse.mkdir()
    original = Path.lstat

    def fake_lstat(path: Path, *args: object, **kwargs: object) -> object:
        info = original(path)
        if path == reparse:
            return SimpleNamespace(st_mode=info.st_mode, st_nlink=info.st_nlink, st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))
        return info

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(ValueError, match="reparse"):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)}, worktree=worktree)


def test_simulated_dangling_reparse_root_rejected(checkout: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _, data, _ = checkout
    original = Path.lstat
    data.rmdir()

    def fake_lstat(path: Path, *args: object, **kwargs: object) -> object:
        if path == data:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_nlink=1, st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024))
        return original(path)

    monkeypatch.setattr(Path, "lstat", fake_lstat)
    with pytest.raises(ValueError, match="reparse"):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)})


@pytest.mark.skipif(sys.platform == "win32", reason="Windows coverage uses unprivileged junctions")
@pytest.mark.parametrize("name,dangling", [("research_data", True), ("alias", False)])
def test_symlink_in_worktree_rejected(checkout: tuple[Path, Path, Path], name: str, dangling: bool) -> None:
    primary, data, worktree = checkout
    target = primary / "missing" if dangling else data
    (worktree / name).symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError):
        DataRoots.from_env({DATA_ROOT_ENV: str(data)}, worktree=worktree)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junction regression")
def test_actual_windows_junction_rejected_without_touching_target(checkout: tuple[Path, Path, Path]) -> None:
    _, data, worktree = checkout
    (data / "sentinel").write_bytes(b"retained")
    junction = worktree / "alias"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(junction), str(data)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    try:
        with pytest.raises(ValueError, match="reparse"):
            DataRoots.from_env({DATA_ROOT_ENV: str(data)}, worktree=worktree)
    finally:
        # Remove only the junction itself; never recursively delete its target.
        os.rmdir(junction)
    assert (data / "sentinel").read_bytes() == b"retained"

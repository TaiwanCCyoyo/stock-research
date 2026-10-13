"""Synthetic checkout tests for shared paths and worktree isolation."""

import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots, _check_tree, _checked_path


def fixture_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=" + str(root.parent / "no-hooks"),
            "-c",
            "commit.gpgSign=false",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.test",
            "-C",
            str(root),
            *arguments,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def init_fixture_repo(primary: Path) -> None:
    primary.mkdir()
    fixture_git(primary, "-c", "init.templateDir=", "init", "--initial-branch=main")
    fixture_git(primary, "commit", "--allow-empty", "-m", "Synthetic fixture")


def replace_git_marker(worktree: Path, content: bytes) -> None:
    """Overwrite an existing synthetic marker without Windows _O_CREAT."""
    with (worktree / ".git").open("r+b") as stream:
        stream.write(content)
        stream.truncate()


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, Path, Path]:
    primary = tmp_path / "primary"
    init_fixture_repo(primary)
    data = primary / "research_data"
    data.mkdir()
    worktree = primary / ".worktrees" / "task"
    fixture_git(primary, "worktree", "add", "--detach", str(worktree), "HEAD")
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


@pytest.mark.parametrize("name", [".git", "research_cache", "tasks", "stock-data-downloader", "research_data"])
@pytest.mark.parametrize("child", [False, True])
def test_canonical_roots_never_count_as_worktrees(checkout: tuple[Path, Path, Path], name: str, child: bool) -> None:
    primary, data, _ = checkout
    candidate = primary / name
    if child:
        candidate /= "child"
    candidate.mkdir(parents=True, exist_ok=True)
    with pytest.raises(ValueError, match="protected primary root"):
        DataRoots(primary, data).validate_worktree(candidate)


def test_ancestor_of_canonical_roots_rejected(checkout: tuple[Path, Path, Path]) -> None:
    primary, data, _ = checkout
    with pytest.raises(ValueError, match="protected primary root"):
        DataRoots(primary, data).validate_worktree(primary.parent)


@pytest.mark.parametrize("git_marker", ["missing", "directory", "file"])
def test_nonregistered_directory_rejected(checkout: tuple[Path, Path, Path], git_marker: str) -> None:
    primary, data, worktree = checkout
    fake = primary.parent / "nonregistered"
    fake.mkdir()
    if git_marker == "directory":
        (fake / ".git").mkdir()
    elif git_marker == "file":
        (fake / ".git").write_bytes((worktree / ".git").read_bytes())
    expected = "not registered" if git_marker == "file" else "regular .git file"
    with pytest.raises(ValueError, match=expected):
        DataRoots(primary, data).validate_worktree(fake)


def test_fake_git_pointer_fails_closed(checkout: tuple[Path, Path, Path]) -> None:
    primary, data, worktree = checkout
    replace_git_marker(worktree, b"gitdir: missing-admin-directory")
    with pytest.raises(ValueError, match="Git worktree identity check failed"):
        DataRoots(primary, data).validate_worktree(worktree)


def test_registered_path_cannot_point_at_primary_git_directory(checkout: tuple[Path, Path, Path]) -> None:
    primary, data, worktree = checkout
    replace_git_marker(worktree, f"gitdir: {(primary / '.git').as_posix()}\n".encode("utf-8"))
    with pytest.raises(ValueError, match="identity|administration"):
        DataRoots(primary, data).validate_worktree(worktree)


def test_registered_worktree_using_foreign_git_metadata_rejected(checkout: tuple[Path, Path, Path]) -> None:
    primary, data, worktree = checkout
    foreign = primary.parent / "foreign-primary"
    init_fixture_repo(foreign)
    foreign_worktree = primary.parent / "foreign-worktree"
    fixture_git(foreign, "worktree", "add", "--detach", str(foreign_worktree), "HEAD")
    replace_git_marker(worktree, (foreign_worktree / ".git").read_bytes())
    with pytest.raises(ValueError, match="identity does not match"):
        DataRoots(primary, data).validate_worktree(worktree)


def test_foreign_registered_worktree_not_registered_with_primary(checkout: tuple[Path, Path, Path]) -> None:
    primary, data, _ = checkout
    foreign = primary.parent / "foreign-primary"
    init_fixture_repo(foreign)
    foreign_worktree = primary.parent / "foreign-worktree"
    fixture_git(foreign, "worktree", "add", "--detach", str(foreign_worktree), "HEAD")
    with pytest.raises(ValueError, match="not registered"):
        DataRoots(primary, data).validate_worktree(foreign_worktree)


def test_git_failure_preserves_diagnostics(checkout: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    primary, data, worktree = checkout

    def failed_git(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["git"], 128, stdout="", stderr="fatal: fixture identity failure")

    monkeypatch.setattr(subprocess, "run", failed_git)
    with pytest.raises(ValueError, match="128.*fatal: fixture identity failure"):
        DataRoots(primary, data).validate_worktree(worktree)


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


def legacy_tree_check(worktree: Path) -> None:
    """The traversal used before the linear walk: every entry re-checks all of its ancestors."""

    def walk_error(error: OSError) -> None:
        raise error

    for directory, directories, files in os.walk(worktree, followlinks=False, onerror=walk_error):
        _checked_path(Path(directory))
        for name in (*directories, *files):
            _checked_path(Path(directory) / name)


def build_clean(tree: Path, outside: Path) -> None:
    (tree / "a" / "b" / "c").mkdir(parents=True)
    (tree / "a" / "b" / "c" / "ok.txt").write_text("x", encoding="utf-8")
    (tree / "top.txt").write_text("y", encoding="utf-8")


def build_deep_hardlink(tree: Path, outside: Path) -> None:
    build_clean(tree, outside)
    os.link(outside / "shared.bin", tree / "a" / "b" / "c" / "alias.bin")


def build_top_hardlink(tree: Path, outside: Path) -> None:
    build_clean(tree, outside)
    os.link(outside / "shared.bin", tree / "alias.bin")


def build_symlink_file(tree: Path, outside: Path) -> None:
    build_clean(tree, outside)
    try:
        (tree / "a" / "link.bin").symlink_to(outside / "shared.bin")
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")


def build_symlink_dir(tree: Path, outside: Path) -> None:
    build_clean(tree, outside)
    try:
        (tree / "a" / "b" / "linkdir").symlink_to(outside / "dir", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")


def build_dangling_symlink(tree: Path, outside: Path) -> None:
    build_clean(tree, outside)
    try:
        (tree / "dangling").symlink_to(outside / "missing", target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlink creation unavailable: {error}")


def build_junction(tree: Path, outside: Path) -> None:
    if sys.platform != "win32":
        pytest.skip("junctions are Windows only")
    build_clean(tree, outside)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(tree / "a" / "b" / "junction"), str(outside / "dir")], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "build,rejected",
    [
        (build_clean, False),
        (build_deep_hardlink, True),
        (build_top_hardlink, True),
        (build_symlink_file, True),
        (build_symlink_dir, True),
        (build_dangling_symlink, True),
        (build_junction, True),
    ],
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_linear_tree_check_matches_the_per_entry_ancestor_check(tmp_path: Path, build: Callable[[Path, Path], None], rejected: bool) -> None:
    """Differential guard: the cheaper walk must accept and reject exactly what the old one did."""
    outside = tmp_path / "outside"
    (outside / "dir").mkdir(parents=True)
    (outside / "shared.bin").write_bytes(b"shared")
    tree = tmp_path / "tree"
    tree.mkdir()
    build(tree, outside)
    junction = tree / "a" / "b" / "junction"
    try:
        outcomes = []
        for check in (legacy_tree_check, _check_tree):
            try:
                check(tree)
                outcomes.append("accepted")
            except ValueError:
                outcomes.append("rejected")
        assert outcomes == ["rejected" if rejected else "accepted"] * 2
    finally:
        if junction.exists() and sys.platform == "win32":
            os.rmdir(junction)  # remove only the junction itself; never its target
    assert (outside / "shared.bin").read_bytes() == b"shared"


def test_linear_tree_check_does_one_lstat_per_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cost guard without timing: lstat calls stay equal to entries, not entries times depth."""
    deep = tmp_path / "t" / "a" / "b" / "c" / "d" / "e" / "f"
    deep.mkdir(parents=True)
    for index in range(20):
        (deep / f"file{index}.txt").write_text("x", encoding="utf-8")
    calls = 0
    original = Path.lstat

    def counting_lstat(path: Path, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(Path, "lstat", counting_lstat)
    checked = _check_tree(tmp_path / "t")
    assert checked == 6 + 20  # directories a..f plus the files
    assert calls == checked

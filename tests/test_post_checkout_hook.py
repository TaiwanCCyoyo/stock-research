"""Functional tests for .githooks/post-checkout's safety guards.

Exercises the hook against real throwaway git repos/worktrees rather than
mocking git, since the guards it must get right (never touch the main
checkout, never fire on an ordinary branch switch, never alias the main
checkout's price cache into a worktree) are exactly the kind of thing a mock
would hide a regression in — the last of those, when it regressed, cost days
of re-downloadable data.

Covers the guard conditions that must hold for *every* checkout (the
higher-risk surface for a hook wired to fire on every `git checkout` and
`git worktree add` repo-wide), plus a scratch submodule shaped like
shioaji_stock_prices for the data-seeding behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

HOOK_PATH = Path(__file__).resolve().parents[1] / ".githooks" / "post-checkout"
ZERO_SHA = "0" * 40
SOME_SHA = "1" * 40

# file:// submodule URLs are blocked by default (CVE-2022-39253); only needed
# for these tests because the test double lives on the local filesystem —
# the real shioaji_stock_prices submodule uses a normal https remote.
_ALLOW_FILE_PROTOCOL_ENV = {**os.environ, "GIT_ALLOW_PROTOCOL": "file"}


def _is_link(path: Path) -> bool:
    """True for a POSIX symlink or an NTFS junction.

    `Path.is_symlink()` returns False for a junction, which is what made the
    old hook's `[ ! -L ]` guard blind to the link it had just created — so
    the reparse-point attribute has to be checked directly on Windows.
    """
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    return bool(path.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def _run_git(args: list[str], cwd: Path, *, allow_file_protocol: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=_ALLOW_FILE_PROTOCOL_ENV if allow_file_protocol else None,
    )
    return result


def _shell_executable() -> str:
    shell = shutil.which("sh")
    if shell:
        return shell
    git = shutil.which("git")
    if os.name == "nt" and git:
        git_directory = Path(git).parent
        for candidate in (git_directory / "sh.exe", git_directory.parent / "bin" / "sh.exe", git_directory.parent / "usr" / "bin" / "sh.exe"):
            if candidate.is_file():
                return str(candidate)
    pytest.skip("Git shell unavailable; real checkout-hook execution cannot be verified")


def _run_hook(cwd: Path, prev: str, new: str = SOME_SHA, flag: str = "1", *, allow_file_protocol: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_shell_executable(), str(HOOK_PATH), prev, new, flag],
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_ALLOW_FILE_PROTOCOL_ENV if allow_file_protocol else None,
    )


@pytest.fixture()
def main_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "main"
    repo.mkdir()
    _run_git(["init", "-q"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    _run_git(["config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _run_git(["add", "README.md"], repo)
    _run_git(["commit", "-q", "-m", "init"], repo)
    return repo


def test_hook_is_a_noop_in_the_main_checkout(main_repo: Path) -> None:
    result = _run_hook(main_repo, prev=ZERO_SHA)

    assert result.returncode == 0
    assert result.stdout == ""


def test_hook_is_a_noop_on_an_ordinary_branch_switch_in_a_worktree(main_repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt"
    _run_git(["worktree", "add", "-b", "feature", str(worktree)], main_repo)

    result = _run_hook(worktree, prev=SOME_SHA)

    assert result.returncode == 0
    assert result.stdout == ""


def test_hook_does_not_touch_a_worktree_with_no_submodule(main_repo: Path, tmp_path: Path) -> None:
    worktree = tmp_path / "wt2"
    _run_git(["worktree", "add", "-b", "feature2", str(worktree)], main_repo)

    result = _run_hook(worktree, prev=ZERO_SHA)

    assert result.returncode == 0
    # No shioaji_stock_prices submodule in this scratch repo, so the
    # data-symlink block's `[ -d "$main_data" ]` guard must skip cleanly
    # rather than erroring on a missing path.
    assert "failed to link" not in result.stdout
    assert not (worktree / "shioaji_stock_prices").exists()


def test_hook_script_exists_and_is_executable() -> None:
    assert HOOK_PATH.is_file()
    _shell_executable()


@pytest.fixture()
def main_repo_with_submodule(tmp_path: Path) -> Path:
    """A scratch repo shaped like this repo's shioaji_stock_prices submodule:
    `data/stock_category.json5` tracked by the submodule, plus (in the main
    checkout only) gitignored cache files standing in for the real ~18GB
    price cache — one of each class the hook must treat differently.
    """
    sub_source = tmp_path / "sub_source"
    sub_source.mkdir()
    _run_git(["init", "-q"], sub_source)
    _run_git(["config", "user.email", "test@example.com"], sub_source)
    _run_git(["config", "user.name", "Test"], sub_source)
    (sub_source / "data").mkdir()
    (sub_source / "data" / "stock_category.json5").write_text("{}\n", encoding="utf-8")
    _run_git(["add", "data/stock_category.json5"], sub_source)
    _run_git(["commit", "-q", "-m", "init"], sub_source)

    repo = tmp_path / "main"
    repo.mkdir()
    _run_git(["init", "-q"], repo)
    _run_git(["config", "user.email", "test@example.com"], repo)
    _run_git(["config", "user.name", "Test"], repo)
    _run_git(["submodule", "add", str(sub_source), "shioaji_stock_prices"], repo, allow_file_protocol=True)
    modules = [
        "scripts/__init__.py",
        "scripts/seed_worktree_inputs.py",
        "research_core/__init__.py",
        "research_core/artifact_store.py",
    ]
    for name in modules:
        destination = repo / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(HOOK_PATH.parents[1] / name, destination)
    _run_git(["add", *modules], repo)
    _run_git(["commit", "-q", "-m", "add submodule and seeding modules"], repo)

    main_data = repo / "shioaji_stock_prices" / "data"
    # Read-set: what this repo's loader/universe/dashboard actually open.
    (main_data / "price_daily.parquet").write_text("parquet stand-in\n", encoding="utf-8")
    (main_data / "2330_day.csv").write_text("daily bars\n", encoding="utf-8")
    quality_report = main_data / "data_quality_report.json"
    quality_report.write_bytes(b'{"source":"synthetic","missing_symbols":[]}\n')
    os.utime(quality_report, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    legacy_daily = main_data / "adjusted_prices" / "daily"
    legacy_daily.mkdir(parents=True)
    (legacy_daily / "2330_day.csv").write_text("legacy adjusted daily bars\n", encoding="utf-8")
    with closing(sqlite3.connect(main_data / "symbol_meta.sqlite")) as database:
        database.execute("CREATE TABLE symbols(code TEXT PRIMARY KEY, name TEXT NOT NULL)")
        database.execute("INSERT INTO symbols VALUES (?, ?)", ("2330", "synthetic issuer"))
        database.commit()
    # Producer-side only: must NOT be copied (15.3GB and 642MB in reality).
    (main_data / "2330_min.csv").write_text("minute bars\n", encoding="utf-8")
    (main_data / "official_daily.sqlite").write_text("official db\n", encoding="utf-8")
    (main_data / "raw").mkdir()
    (main_data / "raw" / "staging.json").write_text("{}\n", encoding="utf-8")
    return repo


def test_hook_copies_only_the_read_set_and_never_links(main_repo_with_submodule: Path, tmp_path: Path) -> None:
    """The hook must seed the worktree by COPYING the consumer read-set, and
    must not leave a link behind.

    An earlier design linked the whole data/ directory (symlink, or an NTFS
    junction where Windows lacked SeCreateSymbolicLinkPrivilege). That made
    the worktree's data/ an alias for the main checkout's, so a recursive
    delete aimed at the worktree traversed it into main: `git worktree
    remove` destroyed ~4000 rate-limited per-symbol CSVs that way on
    2026-08-13. The invariant is therefore inverted from that design — a
    write through the worktree's data/ must NOT reach the main checkout.
    """
    main_data = main_repo_with_submodule / "shioaji_stock_prices" / "data"
    source_before = {path.relative_to(main_data): path.read_bytes() for path in main_data.rglob("*") if path.is_file()}
    source_mtimes = {path.relative_to(main_data): path.stat().st_mtime_ns for path in main_data.rglob("*") if path.is_file()}
    worktree = tmp_path / "wt"
    _run_git(["worktree", "add", "-b", "feature", str(worktree)], main_repo_with_submodule)

    result = _run_hook(worktree, prev=ZERO_SHA, allow_file_protocol=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "input snapshot incomplete" not in result.stdout + result.stderr
    worktree_data = worktree / "shioaji_stock_prices" / "data"
    summaries = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
    assert len(summaries) == 1, result.stdout + result.stderr
    summary = summaries[0]
    assert summary["files"] == 5
    assert summary["existing_preserved"] == 0
    receipt_path = Path(summary["receipt_path"])
    assert receipt_path.is_relative_to(worktree / ".tmp")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "worktree-input-snapshot.v1"
    assert {record["path"] for record in receipt["files"]} == {
        "2330_day.csv",
        "data_quality_report.json",
        "price_daily.parquet",
        "symbol_meta.sqlite",
        "adjusted_prices/daily/2330_day.csv",
    }
    assert next(record for record in receipt["files"] if record["path"] == "symbol_meta.sqlite")["mode"] == "consistent_sqlite_backup_not_live_db_file_copy"
    assert summary["bytes_copied"] == receipt["bytes_copied"] > 0
    quality_record = next(record for record in receipt["files"] if record["path"] == "data_quality_report.json")
    quality_relative = Path("data_quality_report.json")
    quality_hash = hashlib.sha256(source_before[quality_relative]).hexdigest()
    assert quality_record["sha256"] == quality_hash
    assert quality_record["source"] == str(main_data / quality_relative)
    assert quality_record["mode"] == "stable_file_copy"
    assert quality_record["bytes"] == len(source_before[quality_relative])
    assert quality_record["mtime_ns"] == source_mtimes[quality_relative]

    # The read-set is present, so backtests can run in the worktree.
    assert (worktree_data / "price_daily.parquet").read_text(encoding="utf-8") == "parquet stand-in\n"
    assert (worktree_data / "2330_day.csv").read_text(encoding="utf-8") == "daily bars\n"
    assert (worktree_data / quality_relative).read_bytes() == source_before[quality_relative]
    assert (worktree_data / quality_relative).stat().st_mtime_ns == source_mtimes[quality_relative]
    assert (worktree_data / "adjusted_prices/daily/2330_day.csv").read_text(encoding="utf-8") == "legacy adjusted daily bars\n"
    with closing(sqlite3.connect((worktree_data / "symbol_meta.sqlite").as_uri() + "?mode=ro", uri=True)) as database:
        assert database.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        assert database.execute("SELECT code, name FROM symbols").fetchall() == [("2330", "synthetic issuer")]
    # git owns the submodule-tracked file; the hook must not overwrite it.
    assert (worktree_data / "stock_category.json5").is_file()

    # Producer-side bulk stays behind — this is the 98% of the cache that
    # makes a full copy unaffordable and that nothing here reads.
    assert not (worktree_data / "2330_min.csv").exists()
    assert not (worktree_data / "official_daily.sqlite").exists()
    assert not (worktree_data / "raw").exists()

    assert not _is_link(worktree_data), "the hook left a link where a real directory was expected"
    assert all(not _is_link(worktree_data / record["path"]) for record in receipt["files"])

    repeated = _run_hook(worktree, prev=ZERO_SHA, allow_file_protocol=True)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "input snapshot incomplete" not in repeated.stdout + repeated.stderr
    repeat_summaries = [json.loads(line) for line in repeated.stdout.splitlines() if line.startswith("{")]
    assert len(repeat_summaries) == 1, repeated.stdout + repeated.stderr
    repeat_summary = repeat_summaries[0]
    assert repeat_summary["files"] == 0 and repeat_summary["existing_preserved"] == 5
    repeat_receipt = json.loads(Path(repeat_summary["receipt_path"]).read_text(encoding="utf-8"))
    preserved_quality = next(record for record in repeat_receipt["preserved_inventory"] if record["path"] == "data_quality_report.json")
    assert preserved_quality["sha256"] == quality_hash and preserved_quality["mtime_ns"] == source_mtimes[quality_relative]
    assert preserved_quality["mode"] == "existing_snapshot_preserved" and preserved_quality["current_source_byte_match"] is True
    assert (worktree_data / quality_relative).read_bytes() == source_before[quality_relative]
    assert (worktree_data / quality_relative).stat().st_mtime_ns == source_mtimes[quality_relative]

    (worktree_data / "written_from_worktree.txt").write_text("scratch\n", encoding="utf-8")

    assert not (main_data / "written_from_worktree.txt").exists(), (
        "a write through the worktree's data/ reached the main checkout: data/ is linked, not copied, "
        "which is the aliasing that let `git worktree remove` destroy the main price cache."
    )
    assert {path.relative_to(main_data): path.read_bytes() for path in main_data.rglob("*") if path.is_file()} == source_before
    assert {path.relative_to(main_data): path.stat().st_mtime_ns for path in main_data.rglob("*") if path.is_file()} == source_mtimes

"""Exercise the real configured hook, including its upstream environment."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def setup_hook(tmp_path: Path) -> Path:
    repo = tmp_path / "hook fixture with spaces"
    repo.mkdir()
    git(repo, "init", "--quiet")
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    upstream = next(item for item in config["repos"] if item["repo"].endswith("/pre-commit-hooks"))
    hook = next(item for item in upstream["hooks"] if item["id"] == "check-added-large-files")
    expected = "python scripts/check_added_large_files.py"
    assert hook["entry"] == expected
    configured = {**hook, "entry": f'python "{(ROOT / "scripts/check_added_large_files.py").as_posix()}"'}
    (repo / ".pre-commit-config.yaml").write_text(yaml.safe_dump({"repos": [{**upstream, "hooks": [configured]}]}), encoding="utf-8")
    return repo


def write_sized(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": "1.5.0", "plugins_used": [], "filters_used": [], "results": {}}).encode()
    assert size >= len(payload)
    path.write_bytes(payload + b" " * (size - len(payload)))


def run_hook(repo: Path, relative: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pre_commit", "run", "check-added-large-files", "--files", relative],
        cwd=repo,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    ("relative", "size", "expected"),
    [
        (".secrets.baseline", 1024 * 1024, 0),
        (".secrets.baseline", 1024 * 1024 + 1, 1),
        ("ordinary.json", 500 * 1024, 0),
        ("ordinary.json", 500 * 1024 + 1, 1),
        ("nested/.secrets.baseline", 500 * 1024 + 1, 1),
    ],
)
def test_exact_limits_in_real_hook(tmp_path: Path, relative: str, size: int, expected: int) -> None:
    repo = setup_hook(tmp_path)
    write_sized(repo / relative, size)
    git(repo, "add", "--", relative)
    result = run_hook(repo, relative)
    assert result.returncode == expected, result.stdout + result.stderr
    if expected:
        assert "exceeds" in result.stdout + result.stderr


def test_actual_audited_baseline_passes(tmp_path: Path) -> None:
    repo = setup_hook(tmp_path)
    (repo / ".secrets.baseline").write_bytes((ROOT / ".secrets.baseline").read_bytes())
    git(repo, "add", "--", ".secrets.baseline")
    result = run_hook(repo, ".secrets.baseline")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("relative", "expected"), [(".secrets.baseline", 1), ("ordinary.json", 0)])
def test_existing_files_keep_exact_policy(tmp_path: Path, relative: str, expected: int) -> None:
    repo = setup_hook(tmp_path)
    write_sized(repo / relative, 128)
    git(repo, "add", "--", relative)
    git(
        repo,
        "-c",
        "user.name=Hook Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "--quiet",
        "-m",
        "Initial fixture",
    )
    write_sized(repo / relative, 1024 * 1024 + 1)
    git(repo, "add", "--", relative)
    result = run_hook(repo, relative)
    # Existing ordinary files retain upstream added-only behavior. The root
    # baseline still has its approved cap when modified, not only when added.
    assert result.returncode == expected, result.stdout + result.stderr


def test_existing_upstream_lfs_behavior_is_preserved(tmp_path: Path) -> None:
    repo = setup_hook(tmp_path)
    (repo / ".gitattributes").write_text("ordinary.json filter=lfs\n", encoding="utf-8")
    write_sized(repo / "ordinary.json", 500 * 1024 + 1)
    # Attribute inspection is the upstream behavior; avoid invoking a machine's
    # optional LFS clean process in this synthetic fixture.
    git(repo, "-c", "filter.lfs.clean=", "-c", "filter.lfs.required=false", "add", "--", ".gitattributes", "ordinary.json")
    result = run_hook(repo, "ordinary.json")
    assert result.returncode == 0, result.stdout + result.stderr

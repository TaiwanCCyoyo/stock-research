"""Real Windows deletion in a wholly synthetic Git repository and shared store."""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from research_core.artifact_store import file_digest
from research_core.research_data_paths import DATA_ROOT_ENV, DataRoots

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="requires actual Windows Git and PowerShell deletion")


def run(*args: str, cwd: Path, env: dict[str, str] | None = None) -> str:
    return subprocess.run(args, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def inventory(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): {"bytes": p.stat().st_size, "sha256": file_digest(p)} for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("readonly", [False, True])
def test_real_worktree_force_and_powershell_recursive_deletion_preserve_shared_files(tmp_path: Path, readonly: bool):
    primary = tmp_path / "synthetic primary with spaces"
    primary.mkdir()
    run("git", "init", "-b", "main", cwd=primary)
    # Test-only local repo has no project hooks, submodule or real data.
    run("git", "config", "user.name", "Synthetic fixture", cwd=primary)
    run("git", "config", "user.email", "fixture@example.invalid", cwd=primary)
    (primary / "tracked.txt").write_text("invented content\n")
    run("git", "add", "tracked.txt", cwd=primary)
    run("git", "commit", "-m", "test fixture", cwd=primary)
    data = primary / "research_data"
    (data / "features/v1").mkdir(parents=True)
    (data / "features/v1/invented.json").write_bytes(b'{"stock":"INVENTED","MA20":20}')
    (data / "catalog.json").write_bytes(b'{"synthetic":true}')
    if readonly:
        for file in data.rglob("*"):
            if file.is_file():
                file.chmod(0o444)
    baseline = inventory(data)
    for deletion in ("git", "powershell"):
        target = primary / ".worktrees" / deletion
        run("git", "worktree", "add", "--detach", str(target), "HEAD", cwd=primary)
        roots = DataRoots.from_env({DATA_ROOT_ENV: str(data)}, worktree=target)
        shared = roots.artifact_path("data", "features/v1/invented.json")
        assert shared.read_bytes() == b'{"stock":"INVENTED","MA20":20}'
        assert os.path.samefile(shared, data / "features/v1/invented.json")
        (target / "untracked.txt").write_text("synthetic disposable file")
        roots.validate_worktree(target)
        # Verify exact absolute target before either recursive operation.
        absolute = target.absolute()
        assert absolute.is_relative_to(primary / ".worktrees")
        assert absolute != primary and not data.is_relative_to(absolute)
        assert (absolute / ".git").is_file()
        if deletion == "git":
            run("git", "worktree", "remove", "--force", str(absolute), cwd=primary)
        else:
            env = {**os.environ, "RESEARCH_DELETE_TEST_TARGET": str(absolute)}
            run(
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Stop'; Remove-Item -LiteralPath $env:RESEARCH_DELETE_TEST_TARGET -Recurse -Force",
                cwd=primary,
                env=env,
            )
            run("git", "worktree", "prune", cwd=primary)
        assert not absolute.exists()
        assert inventory(data) == baseline
    receipt = {
        "schema": "research-data-windows-deletion-test.v1",
        "windows": platform.platform(),
        "python": platform.python_version(),
        "git": run("git", "--version", cwd=primary),
        "powershell": run("powershell", "-NoProfile", "-Command", "$PSVersionTable.PSVersion.ToString()", cwd=primary),
        "commands": ["git worktree remove --force", "PowerShell Remove-Item -LiteralPath -Recurse -Force"],
        "synthetic_only": True,
        "readonly": readonly,
        "before": baseline,
        "after": inventory(data),
        "worktrees_removed": 2,
    }
    print(json.dumps(receipt))  # noqa: T201 - Retained E2E diagnostic receipt.
    if readonly:
        for file in data.rglob("*"):
            if file.is_file():
                file.chmod(0o600)

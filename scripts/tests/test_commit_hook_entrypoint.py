"""Exercise the actual Git hook with a harmless uv stand-in, including on Windows."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_commit_hook_forwards_arguments_and_optional_groups(tmp_path: Path) -> None:
    shell = shutil.which("sh")
    if shell is None and (git := shutil.which("git")):
        candidate = Path(git).resolve().parents[1] / "bin" / "sh.exe"
        if candidate.is_file():
            shell = str(candidate)
    if shell is None:
        pytest.skip("Git's shell is not installed")
    fake_uv = tmp_path / "uv"
    fake_uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit 17\n', encoding="utf-8")
    fake_uv.chmod(0o755)
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [shell, ".githooks/pre-commit", "argument with spaces"],
        cwd=root,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 17, result.stdout + result.stderr
    arguments = result.stdout.splitlines()
    assert arguments[:7] == ["run", "--group", "dev", "--group", "viewer", "--group", "static-report"]
    assert arguments[7:10] == ["python", "-m", "pre_commit"]
    assert "--hook-type=pre-commit" in arguments
    assert arguments[-2:] == ["--", "argument with spaces"]

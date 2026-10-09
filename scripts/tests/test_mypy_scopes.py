"""Functional checks use real Mypy, not a successful fake checker."""

from __future__ import annotations

import importlib.util
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CONFIG = yaml.safe_load((REPO / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
LOCAL = next(repo for repo in CONFIG["repos"] if repo["repo"] == "local")
ENTRY = shlex.split(next(hook for hook in LOCAL["hooks"] if hook["id"] == "mypy")["entry"])
assert ENTRY[:3] == ["uv", "run", "python"]
SOURCE = REPO / ENTRY[3]
assert SOURCE.resolve().is_relative_to(REPO.resolve())
SPEC = importlib.util.spec_from_file_location("scope_hook_under_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout with spaces"
    (root / "scripts").mkdir(parents=True)
    (root / ENTRY[3]).write_bytes(SOURCE.read_bytes())
    (root / "pyproject.toml").write_text(
        '[tool.mypy]\ncheck_untyped_defs = true\nexplicit_package_bases = true\nexclude = ["^tasks/"]\n',
        encoding="utf-8",
    )
    return root


def write(root: Path, relative: str, text: str) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return relative


def invoke(root: Path, files: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *ENTRY[3:], *files],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_actual_checker_accepts_same_named_modules(checkout: Path) -> None:
    files = [write(checkout, f"tasks/{task}/candidates/two_b.py", "value: int = 1\n") for task in ("20260101-first", "20260102-second")]
    result = invoke(checkout, files)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("Success:") == 2


def test_wrong_task_fails_without_skipping_later_group(checkout: Path) -> None:
    files = [
        write(checkout, "tasks/20260101-first/candidates/two_b.py", 'value: int = "wrong"\n'),
        write(checkout, "tasks/20260102-second/candidates/two_b.py", "value: int = 1\n"),
    ]
    result = invoke(checkout, files)
    assert result.returncode != 0
    assert "Incompatible types" in result.stdout
    assert "Success:" in result.stdout
    assert "Duplicate module" not in result.stdout


def test_wrong_root_fails_and_task_still_checked(checkout: Path) -> None:
    files = [
        write(checkout, "root_module.py", 'value: int = "wrong"\n'),
        write(checkout, "tasks/20260101-first/candidates/two_b.py", "value: int = 1\n"),
    ]
    result = invoke(checkout, files)
    assert result.returncode != 0
    assert "Incompatible types" in result.stdout
    assert "Success:" in result.stdout


def test_every_received_filename_is_assigned_once(checkout: Path) -> None:
    files = [write(checkout, f"tasks/{number % 12:02d}-study/candidates/module_{number}.py", "value = 1\n") for number in range(44)]
    files += [write(checkout, f"scripts/module_{number}.py", "value = 1\n") for number in range(295)]
    groups = HOOK.group_files(checkout, files)
    received = [(scope / filename).resolve() for scope, group in groups for filename in group]
    assert len(received) == 339
    assert len(set(received)) == 339
    assert set(received) == {(checkout / filename).resolve() for filename in files}


def test_outside_file_is_rejected(checkout: Path) -> None:
    outside = checkout.parent / "outside.py"
    outside.write_text("value = 1\n", encoding="utf-8")
    result = invoke(checkout, ["../outside.py"])
    assert result.returncode == 2
    assert "within the checkout" in result.stderr


def test_task_runtime_import_roots(checkout: Path) -> None:
    write(checkout, "StockProject/engine/__init__.py", "")
    write(checkout, "StockProject/engine/strategy_base.py", "class StrategyBase:\n    pass\n")
    write(checkout, "research_core/__init__.py", "")
    write(checkout, "research_core/contracts.py", "VALUE: int = 1\n")
    write(checkout, "tasks/20260101-first/helpers.py", "VALUE: int = 2\n")
    candidate = write(
        checkout,
        "tasks/20260101-first/candidates/two_b.py",
        "from engine.strategy_base import StrategyBase\n"
        "from research_core.contracts import VALUE\n"
        "from helpers import VALUE as LOCAL\n"
        "class Candidate(StrategyBase):\n    total: int = VALUE + LOCAL\n",
    )
    result = invoke(checkout, [candidate])
    assert result.returncode == 0, result.stdout + result.stderr

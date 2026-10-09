"""Check explicit hook filenames in their runtime package scopes."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path


def group_files(repo_root: Path, filenames: list[str]) -> list[tuple[Path, list[str]]]:
    """Assign every input once; reject missing files and checkout escapes."""
    root = repo_root.resolve(strict=True)
    groups: OrderedDict[Path, list[str]] = OrderedDict()
    for filename in filenames:
        supplied = Path(filename)
        path = (supplied if supplied.is_absolute() else root / supplied).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"filename is not a file within the checkout: {filename}")
        relative = path.relative_to(root)
        scope = root / "tasks" / relative.parts[1] if len(relative.parts) >= 3 and relative.parts[0] == "tasks" else root
        groups.setdefault(scope, []).append(str(path.relative_to(scope)))
    return list(groups.items())


def run_checks(repo_root: Path, filenames: list[str]) -> int:
    """Run all groups with the same interpreter; retain every failure."""
    root = repo_root.resolve(strict=True)
    groups = group_files(root, filenames)
    status = 0
    for scope, files in groups:
        env = os.environ.copy()
        # A task uses its own bare imports; never expose unrelated task roots.
        # Root files retain StockProject.engine identity instead of remapping it.
        bases = [root] if scope == root else [scope, root, root / "StockProject"]
        env["MYPYPATH"] = os.pathsep.join(str(base) for base in bases)
        result = subprocess.run(
            [sys.executable, "-m", "mypy", "--config-file", str(root / "pyproject.toml"), "--explicit-package-bases", *files],
            cwd=scope,
            env=env,
            check=False,
        )
        status |= result.returncode if result.returncode >= 0 else 1
    return status


def main(argv: list[str] | None = None) -> int:
    filenames = sys.argv[1:] if argv is None else argv
    try:
        return run_checks(Path(__file__).resolve().parents[1], filenames)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"Mypy scope setup failed: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

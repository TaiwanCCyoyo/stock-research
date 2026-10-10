"""Regenerate price_daily.parquet from rows.json with the pinned stock-data-downloader.

Stock only consumes the producer's data; it never runs producer code in its tests or CI.
This script is the one place that does, by hand, when the producer's parquet format
changes: it writes rows.json as {code}_day.csv files into a scratch directory, runs the
submodule's build_price_parquet there, and copies the result next to this file.

    uv run python tests/fixtures/price_daily/regenerate.py

Requires the stock-data-downloader submodule to be checked out. Record the submodule
commit in README.md whenever the fixture changes.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]


def write_day_csvs(rows_file: Path, root: Path) -> None:
    rows = json.loads(rows_file.read_text(encoding="utf-8"))
    for code, bars in rows.items():
        lines = ["Date,Open,High,Low,Close,Volume"] + [",".join(str(value) for value in bar) for bar in bars]
        (root / f"{code}_day.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def regenerate(repo_root: Path = REPO_ROOT, fixture_dir: Path = HERE) -> str:
    """Rebuild fixture_dir/price_daily.parquet from fixture_dir/rows.json; return the producer commit."""
    producer = repo_root / "stock-data-downloader"
    script = producer / "scripts" / "build_price_parquet.py"
    if not script.is_file():
        raise SystemExit("check out the stock-data-downloader submodule first: git submodule update --init stock-data-downloader")
    sys.path.insert(0, str(producer))  # the script resolves its config package from the producer root
    spec = importlib.util.spec_from_file_location("producer_build_price_parquet", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    scratch_parent = repo_root / ".tmp"  # ignored scratch area; absent in a fresh clone
    scratch_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_parent) as scratch:
        root = Path(scratch)
        write_day_csvs(fixture_dir / "rows.json", root)
        built = module.build_price_parquet(root)
        shutil.copyfile(built, fixture_dir / "price_daily.parquet")
    return subprocess.run(["git", "-C", str(producer), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    commit = regenerate()
    sys.stdout.write(f"regenerated price_daily.parquet with stock-data-downloader {commit}; record it in README.md\n")


if __name__ == "__main__":
    main()

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
PRODUCER = REPO_ROOT / "stock-data-downloader"


def write_day_csvs(root: Path) -> None:
    rows = json.loads((HERE / "rows.json").read_text(encoding="utf-8"))
    for code, bars in rows.items():
        lines = ["Date,Open,High,Low,Close,Volume"] + [",".join(str(value) for value in bar) for bar in bars]
        (root / f"{code}_day.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    script = PRODUCER / "scripts" / "build_price_parquet.py"
    if not script.is_file():
        raise SystemExit("check out the stock-data-downloader submodule first: git submodule update --init stock-data-downloader")
    sys.path.insert(0, str(PRODUCER))  # the script resolves its config package from the producer root
    spec = importlib.util.spec_from_file_location("producer_build_price_parquet", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with tempfile.TemporaryDirectory(dir=REPO_ROOT / ".tmp") as scratch:
        root = Path(scratch)
        write_day_csvs(root)
        built = module.build_price_parquet(root)
        shutil.copyfile(built, HERE / "price_daily.parquet")
    commit = subprocess.run(["git", "-C", str(PRODUCER), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    sys.stdout.write(f"regenerated price_daily.parquet with stock-data-downloader {commit}; record it in README.md\n")


if __name__ == "__main__":
    main()

"""build_price_parquet output parity and DataLoader parquet staleness fallback.

build_price_parquet.py lives in the stock-data-downloader submodule (generic
data-processing scripts are owned there, not by the main repo) and is loaded
here by file path since it isn't an importable package from this repo.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

from pandas.testing import assert_frame_equal

from StockProject.engine.data_loader import DataLoader

REPO_ROOT = Path(__file__).resolve().parents[1]
_SUBMODULE_ROOT = REPO_ROOT / "stock-data-downloader"

# The script resolves its default data path through the submodule's own
# `config` package, so that root has to be importable before the module is
# executed. Loading it by file path alone is not enough.
if str(_SUBMODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SUBMODULE_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "shioaji_build_price_parquet",
    _SUBMODULE_ROOT / "scripts" / "build_price_parquet.py",
)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
build_price_parquet = _MODULE.build_price_parquet


def write_day_csv(data_root: Path, code: str, rows: list[tuple[str, float, float, float, float, int]]) -> Path:
    path = data_root / f"{code}_day.csv"
    lines = ["Date,Open,High,Low,Close,Volume"]
    for date, open_, high, low, close, volume in rows:
        lines.append(f"{date},{open_},{high},{low},{close},{volume}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def make_data_root(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    write_day_csv(
        root,
        "2330",
        [
            ("2025-01-02", 100.0, 102.0, 99.0, 100.0, 1000),
            ("2025-01-03", 96.0, 97.0, 94.0, 95.0, 1200),
        ],
    )
    write_day_csv(
        root,
        "2454",
        [
            ("2025-01-02", 50.0, 52.0, 49.0, 51.0, 500),
        ],
    )
    return root


def test_build_price_parquet_matches_csv_load_all(tmp_path: Path) -> None:
    csv_root = make_data_root(tmp_path, "csv_only")
    parquet_root = make_data_root(tmp_path, "with_parquet")

    parquet_path = build_price_parquet(parquet_root)

    assert parquet_path.is_file()
    csv_loader = DataLoader(str(csv_root))
    csv_loader.load_all()
    parquet_loader = DataLoader(str(parquet_root))
    parquet_loader.load_all()
    for code in ["2330", "2454"]:
        expected = csv_loader.get_stock_data(code).reset_index(drop=True)
        actual = parquet_loader.get_stock_data(code).reset_index(drop=True)
        # The parquet path is a superset now: build_price_parquet computes the moving
        # averages itself rather than copying them from the CSV, so a bare fixture CSV
        # without those columns produces fewer of them. Real {code}_day.csv files carry
        # them. Every column both paths do produce must still agree exactly.
        shared = sorted(set(actual.columns) & set(expected.columns))
        assert_frame_equal(actual[shared], expected[shared])
        assert {"SMA5", "SMA60", "EMA5", "EMA60"} <= set(actual.columns)


def test_load_all_falls_back_to_csv_for_stale_symbols(tmp_path: Path) -> None:
    root = make_data_root(tmp_path, "data")
    parquet_path = build_price_parquet(root)

    csv_path = write_day_csv(
        root,
        "2330",
        [
            ("2025-01-02", 100.0, 102.0, 99.0, 100.0, 1000),
            ("2025-01-03", 96.0, 97.0, 94.0, 95.0, 1200),
            ("2025-01-06", 95.0, 99.0, 95.0, 98.0, 900),
        ],
    )
    parquet_stat = parquet_path.stat()
    os.utime(csv_path, (parquet_stat.st_atime, parquet_stat.st_mtime + 10))

    loader = DataLoader(str(root))
    loader.load_all()

    stale_symbol = loader.get_stock_data("2330")
    assert len(stale_symbol) == 3
    assert float(stale_symbol.iloc[-1]["RawClose"]) == 98.0
    fresh_symbol = loader.get_stock_data("2454")
    assert len(fresh_symbol) == 1


def test_load_all_uses_parquet_when_up_to_date(tmp_path: Path) -> None:
    root = make_data_root(tmp_path, "data")
    parquet_path = build_price_parquet(root)

    for csv_file in root.glob("*_day.csv"):
        stat = csv_file.stat()
        os.utime(csv_file, (stat.st_atime, parquet_path.stat().st_mtime - 100))

    loader = DataLoader(str(root))
    loader.load_all()

    assert len(loader.get_stock_data("2330")) == 2
    assert len(loader.get_stock_data("2454")) == 1


def test_a_stale_symbol_keeps_the_history_its_csv_does_not_cover(tmp_path: Path) -> None:
    """The staleness fallback must merge, not replace.

    Since 2026-08-30 the parquet is built from the official artifact and reaches
    2010-01-04, while a {code}_day.csv is Shioaji-derived and starts 2018-12-07.
    Swapping a stale symbol's parquet rows for its CSV rows wholesale would silently
    delete years of that symbol's history -- and quietly, since the run still succeeds.
    """
    root = make_data_root(tmp_path, "data")
    parquet_path = build_price_parquet(root)

    # Give the parquet a row the CSV will never have, standing in for the pre-2018
    # history the official artifact supplies.
    import pandas as pd

    df = pd.read_parquet(parquet_path)
    old_row = df[df["Code"] == "2330"].iloc[[0]].copy()
    old_row["Date"] = pd.Timestamp("2015-06-01")
    old_row["ts"] = "2015-06-01"
    old_row["Close"] = 42.0
    pd.concat([df, old_row], ignore_index=True).to_parquet(parquet_path, index=False)

    csv_path = write_day_csv(
        root,
        "2330",
        [
            ("2025-01-02", 100.0, 102.0, 99.0, 100.0, 1000),
            ("2025-01-03", 96.0, 97.0, 94.0, 95.0, 1200),
            ("2025-01-06", 95.0, 99.0, 95.0, 98.0, 900),
        ],
    )
    parquet_stat = parquet_path.stat()
    os.utime(csv_path, (parquet_stat.st_atime, parquet_stat.st_mtime + 10))

    loader = DataLoader(str(root))
    loader.load_all()

    stale_symbol = loader.get_stock_data("2330")
    dates = set(pd.to_datetime(stale_symbol["Date"]).dt.strftime("%Y-%m-%d"))
    assert "2015-06-01" in dates, "the CSV refresh must not delete history the CSV lacks"
    assert "2025-01-06" in dates, "and the CSV's newer bar must still win"
    assert len(stale_symbol) == 4

"""Stock's side of the price_daily.parquet contract, without running producer code.

stock-data-downloader produces price_daily.parquet; Stock only consumes it. These tests
read a small parquet the pinned producer generated from rows.json
(tests/fixtures/price_daily/, see its README) and check that DataLoader reads it
identically to the same rows as day CSVs, and handles stale CSVs correctly. Whether the
producer builds that parquet correctly is tested in the producer's own repository.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from pandas.testing import assert_frame_equal

from StockProject.engine.data_loader import DataLoader

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "price_daily"
ROWS = json.loads((FIXTURE / "rows.json").read_text(encoding="utf-8"))


def build_price_parquet(data_root: Path) -> Path:
    """Stand-in for the producer build: install the producer-generated fixture parquet.

    The copy gets a fresh modification time, so it is newer than the CSVs written before
    it, exactly like a parquet built after them.
    """
    target = data_root / "price_daily.parquet"
    shutil.copyfile(FIXTURE / "price_daily.parquet", target)
    return target


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
    for code, bars in ROWS.items():
        write_day_csv(root, code, [tuple(bar) for bar in bars])
    return root


def test_fixture_parquet_holds_exactly_the_fixture_rows() -> None:
    """Guards against a fixture regenerated from different rows than the CSVs use."""
    import pandas as pd

    df = pd.read_parquet(FIXTURE / "price_daily.parquet")
    dates = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d").tolist()
    columns = [df[name].tolist() for name in ("Open", "High", "Low", "Close")]
    actual = sorted(
        (str(code), date, float(o), float(h), float(low), float(c), int(v))
        for code, date, o, h, low, c, v in zip(df["Code"].tolist(), dates, *columns, df["Volume"].tolist(), strict=True)
    )
    expected = sorted((code, *bar) for code, bars in ROWS.items() for bar in bars)
    assert actual == [tuple(row) for row in expected]


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

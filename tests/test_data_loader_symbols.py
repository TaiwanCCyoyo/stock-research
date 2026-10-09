"""Parity and caching tests for DataLoader.load_symbols (per-symbol loading)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from pytest import MonkeyPatch

from StockProject.engine.data_loader import DataLoader

CA_COLUMNS = [
    "code",
    "ex_date",
    "event_type",
    "previous_close",
    "reference_price",
    "cash_dividend_estimate",
    "price_factor",
    "evidence_status",
]


def write_day_csv(data_root: Path, code: str, rows: list[tuple[str, float, float, float, float, int]]) -> Path:
    path = data_root / f"{code}_day.csv"
    lines = ["Date,Open,High,Low,Close,Volume"]
    for date, open_, high, low, close, volume in rows:
        lines.append(f"{date},{open_},{high},{low},{close},{volume}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_corporate_actions_db(data_root: Path, rows: list[tuple]) -> Path:
    db_path = data_root / "corporate_actions.sqlite"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE corporate_actions ("
            "code TEXT, ex_date TEXT, event_type TEXT, previous_close REAL, "
            "reference_price REAL, cash_dividend_estimate REAL, price_factor REAL, "
            "evidence_status TEXT)"
        )
        conn.executemany(
            f"INSERT INTO corporate_actions ({', '.join(CA_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
    return db_path


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    """Three symbols; 2330 has a cash-dividend corporate action inside its date range."""
    root = tmp_path / "data"
    root.mkdir()
    write_day_csv(
        root,
        "2330",
        [
            ("2025-01-02", 100.0, 102.0, 99.0, 100.0, 1000),
            ("2025-01-03", 96.0, 97.0, 94.0, 95.0, 1200),
            ("2025-01-06", 95.0, 99.0, 95.0, 98.0, 900),
            ("2025-01-07", 98.0, 101.0, 98.0, 101.0, 1100),
        ],
    )
    write_day_csv(
        root,
        "2454",
        [
            ("2025-01-02", 50.0, 52.0, 49.0, 51.0, 500),
            ("2025-01-03", 51.0, 53.0, 50.0, 52.0, 600),
        ],
    )
    write_day_csv(
        root,
        "2603",
        [
            ("2025-01-02", 20.0, 21.0, 19.0, 20.5, 300),
        ],
    )
    write_corporate_actions_db(
        root,
        [
            ("2330", "2025-01-03", "CASH_DIVIDEND", 100.0, 95.0, 5.0, 0.95, "confirmed"),
        ],
    )
    return root


EXPECTED_LAYER_COLUMNS = {
    "RawOpen",
    "RawHigh",
    "RawLow",
    "RawClose",
    "SignalOpen",
    "SignalHigh",
    "SignalLow",
    "SignalClose",
    "SplitAdjustmentFactor",
    "DividendSignalFactor",
    "SignalPricePolicy",
    "CorporateActionTypes",
}


def test_load_all_characterization_with_corporate_action(data_root: Path) -> None:
    """Pin the current load_all() output shape and adjusted values as ground truth."""
    loader = DataLoader(str(data_root))
    loader.load_all()

    df = loader.get_stock_data("2330")

    assert EXPECTED_LAYER_COLUMNS.issubset(df.columns)
    assert list(df["Date"]) == list(pd.to_datetime(["2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"]))
    # Dividend window: 2025-01-03 close 95 < previous_close 100, so the signal
    # price is scaled by 1/price_factor; 2025-01-06 close 98 < 100 keeps the
    # window open; 2025-01-07 close 101 >= 100 marks the dividend as filled.
    assert df.iloc[1]["SignalPricePolicy"] == "cash_dividend_window"
    assert df.iloc[1]["SignalClose"] == pytest.approx(95.0 / 0.95, abs=1e-4)
    assert bool(df.iloc[3]["DividendFilled"]) is True
    assert df.iloc[0]["CorporateActionTypes"] == ""
    assert df.iloc[1]["CorporateActionTypes"] == "CASH_DIVIDEND"


def test_load_symbols_matches_load_all_for_single_symbol(data_root: Path) -> None:
    full = DataLoader(str(data_root))
    full.load_all()
    expected = full.get_stock_data("2454").reset_index(drop=True)

    partial = DataLoader(str(data_root))
    partial.load_symbols(["2454"])
    actual = partial.get_stock_data("2454").reset_index(drop=True)

    assert_frame_equal(actual[sorted(actual.columns)], expected[sorted(expected.columns)])


def test_load_symbols_matches_load_all_for_multiple_symbols_with_corporate_action(data_root: Path) -> None:
    full = DataLoader(str(data_root))
    full.load_all()

    partial = DataLoader(str(data_root))
    partial.load_symbols(["2330", "2454"])

    for code in ["2330", "2454"]:
        expected = full.get_stock_data(code).reset_index(drop=True)
        actual = partial.get_stock_data(code).reset_index(drop=True)
        assert_frame_equal(actual[sorted(actual.columns)], expected[sorted(expected.columns)])


def test_load_symbols_reads_only_requested_files(data_root: Path, monkeypatch: MonkeyPatch) -> None:
    read_paths: list[str] = []
    original_read_csv = pd.read_csv

    def spy_read_csv(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        read_paths.append(os.path.basename(str(path)))
        return original_read_csv(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pd, "read_csv", spy_read_csv)

    loader = DataLoader(str(data_root))
    loader.load_symbols(["2454"])

    assert read_paths == ["2454_day.csv"]


def test_load_symbols_missing_code_yields_empty_frame(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_symbols(["9999"])

    assert loader.get_stock_data("9999").empty


def test_get_corporate_actions_returns_events_for_code(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_symbols(["2330", "2454"])

    events = loader.get_corporate_actions("2330")

    assert len(events) == 1
    assert events.iloc[0]["event_type"] == "CASH_DIVIDEND"
    assert events.iloc[0]["Date"] == pd.Timestamp("2025-01-03")


def test_get_corporate_actions_empty_for_code_without_events(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_symbols(["2454"])

    assert loader.get_corporate_actions("2454").empty


def test_symbol_cache_skips_reread_within_process(data_root: Path, monkeypatch: MonkeyPatch) -> None:
    first = DataLoader(str(data_root))
    first.load_symbols(["2454"])

    read_paths: list[str] = []
    original_read_csv = pd.read_csv

    def spy_read_csv(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        read_paths.append(os.path.basename(str(path)))
        return original_read_csv(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pd, "read_csv", spy_read_csv)

    second = DataLoader(str(data_root))
    second.load_symbols(["2454"])

    assert read_paths == []
    assert_frame_equal(
        second.get_stock_data("2454").reset_index(drop=True),
        first.get_stock_data("2454").reset_index(drop=True),
    )


def test_symbol_cache_invalidates_when_mtime_changes(data_root: Path, monkeypatch: MonkeyPatch) -> None:
    first = DataLoader(str(data_root))
    first.load_symbols(["2454"])

    csv_path = data_root / "2454_day.csv"
    stat = csv_path.stat()
    os.utime(csv_path, (stat.st_atime, stat.st_mtime + 10))

    read_paths: list[str] = []
    original_read_csv = pd.read_csv

    def spy_read_csv(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        read_paths.append(os.path.basename(str(path)))
        return original_read_csv(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pd, "read_csv", spy_read_csv)

    second = DataLoader(str(data_root))
    second.load_symbols(["2454"])

    assert read_paths == ["2454_day.csv"]

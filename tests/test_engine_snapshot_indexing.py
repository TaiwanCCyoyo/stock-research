"""Regression tests for the per-symbol indexing that replaced full-frame scans.

Two hot paths were rewritten because they cost `symbols x bars^2` and `symbols x rows`
respectively, which was invisible at twenty symbols and made a 1,345-symbol run
unfinishable:

  `DataLoader.get_stock_data` selected with
  `self._price_df[self._price_df["Code"].astype(str) == str(code)]`, rebuilding a string
  array over the whole cache for every symbol requested. It now reads `_price_by_code`.

  `BacktestEngine.run` built each day's snapshot with
  `df[df["Date"] == current_date]` per symbol, a full scan per symbol per bar. It now
  reads a `date -> row` dict, and the rows are plain dicts rather than pandas Series.

These tests pin the behaviours that the rewrite could plausibly break, and the first one
exists because it did break during development: `load_symbols` was left without the index,
so `get_stock_data` returned an empty frame for every symbol. Nothing failed loudly -- the
CLI happened to use `load_all` -- but `research_api`, `scripts/stock_research_query.py`
and `mae_analysis.py` all go through `load_symbols` and would have silently found no data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from StockProject.engine.backtest_engine import BacktestEngine
from StockProject.engine.data_loader import DataLoader


def write_day_csv(root: Path, code: str, rows: list[tuple[str, float, float, float, float, int]]) -> None:
    lines = ["Date,Open,High,Low,Close,Volume"]
    for date, open_, high, low, close, volume in rows:
        lines.append(f"{date},{open_},{high},{low},{close},{volume}")
    (root / f"{code}_day.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    write_day_csv(
        root,
        "1111",
        [
            ("2025-01-02", 10.0, 11.0, 9.5, 10.5, 100),
            ("2025-01-03", 10.5, 12.0, 10.0, 11.5, 120),
            ("2025-01-06", 11.5, 12.5, 11.0, 12.0, 90),
        ],
    )
    write_day_csv(
        root,
        "2222",
        [
            ("2025-01-02", 50.0, 51.0, 49.0, 50.5, 200),
            ("2025-01-03", 50.5, 52.0, 50.0, 51.5, 210),
            ("2025-01-06", 51.5, 53.0, 51.0, 52.5, 190),
        ],
    )
    # An empty corporate-actions database keeps the policy branch active without adding
    # adjustments that would obscure the raw values these tests assert on.
    with sqlite3.connect(root / "corporate_actions.sqlite") as conn:
        conn.execute(
            "CREATE TABLE corporate_actions ("
            "code TEXT, ex_date TEXT, event_type TEXT, previous_close REAL, "
            "reference_price REAL, cash_dividend_estimate REAL, price_factor REAL, evidence_status TEXT)"
        )
    return root


def test_get_stock_data_works_after_load_symbols(data_root: Path) -> None:
    """The regression that prompted this file: load_symbols must index too."""
    loader = DataLoader(str(data_root))
    loader.load_symbols(["1111"])

    df = loader.get_stock_data("1111")

    assert not df.empty
    assert list(df["Close"]) == [10.5, 11.5, 12.0]


def test_get_stock_data_returns_only_the_requested_symbol(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    assert set(loader.get_stock_data("2222")["Code"]) == {"2222"}
    assert list(loader.get_stock_data("2222")["Close"]) == [50.5, 51.5, 52.5]


def test_get_stock_data_for_an_unknown_symbol_is_empty(data_root: Path) -> None:
    loader = DataLoader(str(data_root))
    loader.load_all()

    assert loader.get_stock_data("9999").empty


def test_snapshot_rows_are_indexable_by_column_name(data_root: Path) -> None:
    """Strategies read `row["Close"]` and `row.get("Volume", 0.0)`; both must keep working."""
    loader = DataLoader(str(data_root))
    loader.load_all()
    seen: list[dict[str, Any]] = []

    class Recorder:
        def __init__(self, broker: Any, context: dict | None = None) -> None:
            self.broker = broker
            self.context = context or {}

        def warmup(self) -> int:
            return 0

        def on_bar(self, date: Any, data_dict: dict[str, Any]) -> None:
            for code, row in data_dict.items():
                seen.append({"date": date, "code": code, "close": row["Close"], "volume": row.get("Volume", 0.0)})

    class StubBroker:
        initial_cash = 1_000_000
        fee_rate = 0.001425
        positions: dict[str, int] = {}

        def set_execution_prices(self, prices: dict[str, float]) -> None:
            self.prices = prices

        def get_total_value(self, prices: dict[str, float]) -> float:
            return float(self.initial_cash)

        def get_performance(self, prices: dict[str, float]) -> dict[str, Any]:
            return {"final_value": self.initial_cash, "total_pnl": 0.0, "return_rate": 0.0}

    engine = BacktestEngine(StubBroker(), loader)
    engine.run(["1111", "2222"], Recorder, start_date="2025-01-02", end_date="2025-01-06")

    closes = {(str(item["date"])[:10], item["code"]): item["close"] for item in seen}
    assert closes[("2025-01-02", "1111")] == 10.5
    assert closes[("2025-01-06", "2222")] == 52.5
    assert all(item["volume"] > 0 for item in seen)


def test_snapshot_keeps_the_first_row_when_a_date_repeats(data_root: Path) -> None:
    """The old code took `row.iloc[0]`; a plain dict build would keep the last instead."""
    loader = DataLoader(str(data_root))
    loader.load_all()

    duplicated = pd.concat(
        [loader.get_stock_data("1111"), loader.get_stock_data("1111").tail(1).assign(Close=999.0)],
        ignore_index=True,
    )

    class Stub:
        def get_stock_data(self, code: str, adjust: bool = True) -> pd.DataFrame:  # noqa: ARG002
            return duplicated if code == "1111" else pd.DataFrame()

        def set_backtest_window(self, start_date: Any = None, end_date: Any = None) -> None:
            return

        def get_dividends_for_date(self, date: Any) -> pd.DataFrame:
            return pd.DataFrame()

        def get_splits_for_date(self, date: Any) -> pd.DataFrame:
            return pd.DataFrame()

    captured: list[float] = []

    class Recorder:
        def __init__(self, broker: Any, context: dict | None = None) -> None:
            self.broker = broker
            self.context = context or {}

        def warmup(self) -> int:
            return 0

        def on_bar(self, date: Any, data_dict: dict[str, Any]) -> None:
            if "1111" in data_dict and str(date)[:10] == "2025-01-06":
                captured.append(float(data_dict["1111"]["Close"]))

    class StubBroker:
        def set_execution_prices(self, prices: dict[str, float]) -> None:
            return

        def get_total_value(self, prices: dict[str, float]) -> float:
            return 0.0

        def get_performance(self, prices: dict[str, float]) -> dict[str, Any]:
            return {}

    BacktestEngine(StubBroker(), Stub()).run(["1111"], Recorder)

    assert captured == [12.0], "the duplicate row's 999.0 must not win"

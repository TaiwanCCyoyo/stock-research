"""Regression: the backtest entry point applies the live producer read contract."""

from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from research_core import live_producer
from StockProject import backtest_cli

TAIPEI = timezone(timedelta(hours=8))


@pytest.fixture
def live_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "live producer data"
    root.mkdir()
    pd.DataFrame({"Code": ["2330"], "Date": pd.to_datetime(["2026-10-14"]), "Close": [1.0]}).to_parquet(root / "price_daily.parquet")
    with closing(sqlite3.connect(root / "corporate_actions.sqlite")) as database:
        database.execute(
            "CREATE TABLE corporate_actions (code TEXT, ex_date TEXT, event_type TEXT, previous_close REAL, reference_price REAL,"
            " cash_dividend_estimate REAL, price_factor REAL, evidence_status TEXT)"
        )
        database.commit()
    monkeypatch.setenv("STOCK_PRODUCER_DATA_ROOT", str(root))
    monkeypatch.setattr(live_producer, "running_producer_tasks", lambda: [])
    return root


def _at(monkeypatch: pytest.MonkeyPatch, moment: datetime) -> None:
    monkeypatch.setattr(live_producer, "producer_time", lambda now=None: moment)


def _stub_run(monkeypatch: pytest.MonkeyPatch, run: Any) -> None:
    class Loader:
        _price_df = object()

        def __init__(self, **kwargs: Any) -> None:
            pass

        def load_all(self) -> None:
            pass

    monkeypatch.setattr(backtest_cli, "DataLoader", Loader)
    monkeypatch.setattr(backtest_cli, "resolve_codes", lambda value, **kwargs: ([value], None))
    monkeypatch.setattr(backtest_cli, "load_strategy_class", lambda _: type("Strategy", (), {}))
    monkeypatch.setattr(backtest_cli, "run_backtest_pass", run)


def test_backtest_refuses_live_data_in_the_write_window(live_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _at(monkeypatch, datetime(2026, 10, 15, 18, 10, tzinfo=TAIPEI))
    _stub_run(monkeypatch, lambda *args: pytest.fail("backtest must not run during the write window"))
    monkeypatch.setattr(sys, "argv", ["backtest_cli", "--strategy", "unused.py", "--codes", "2330"])
    with pytest.raises(SystemExit) as stopped:
        backtest_cli.main()
    assert stopped.value.code == 1


def test_backtest_fails_when_live_inputs_change_during_the_run(live_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _at(monkeypatch, datetime(2026, 10, 15, 1, 30, tzinfo=TAIPEI))

    def writer_runs_meanwhile(*args: Any) -> dict[str, Any]:
        os.utime(live_root / "price_daily.parquet", ns=(1, 1))
        return {}

    _stub_run(monkeypatch, writer_runs_meanwhile)
    output = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["backtest_cli", "--strategy", "unused.py", "--codes", "2330", "--output", str(output)])
    with pytest.raises(SystemExit) as stopped:
        backtest_cli.main()
    assert stopped.value.code == 1 and not output.exists()


def test_backtest_corporate_action_read_is_read_only(live_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The pinned DataLoader's own SQLite read goes through a read-only connection."""
    from StockProject.engine.data_loader import DataLoader

    opened: list[Path] = []
    original = live_producer.readonly_connect

    def spy(database: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        opened.append(Path(database))
        return original(database, *args, **kwargs)

    monkeypatch.setattr(live_producer, "readonly_connect", spy)
    loader = DataLoader(data_path=live_root)
    backtest_cli.read_sqlite_readonly(loader)
    loader._load_corporate_actions()
    assert opened == [live_root / "corporate_actions.sqlite"]
    assert sys.modules[DataLoader.__module__].sqlite3 is sqlite3

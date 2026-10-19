"""Regression: the backtest entry point applies the live producer read contract."""

from __future__ import annotations

import json
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


def test_backtest_records_live_inputs_changed_during_the_run(live_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _at(monkeypatch, datetime(2026, 10, 15, 1, 30, tzinfo=TAIPEI))

    def writer_runs_meanwhile(*args: Any) -> dict[str, Any]:
        os.utime(live_root / "price_daily.parquet", ns=(1, 1))
        return {"metrics": {"return_rate": 0.0, "max_drawdown_rate": 0.0, "win_rate": None, "total_pnl": 0.0, "final_value": 1.0, "trade_count": 0}}

    _stub_run(monkeypatch, writer_runs_meanwhile)
    output = tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", ["backtest_cli", "--strategy", "unused.py", "--codes", "2330", "--output", str(output)])
    backtest_cli.main()
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["data"]["inputs_changed_during_run"] == ["price_daily"], "the finished run is saved with the change recorded"


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


def _nested_data_dir(live_root: Path) -> Path:
    """A price directory nested in the producer root; its corporate-action DB sits two levels up."""
    data = live_root / "adjusted_prices" / "daily"
    data.mkdir(parents=True)
    (live_root / "price_daily.parquet").replace(data / "price_daily.parquet")
    return data


def _run_with_real_loader(monkeypatch: pytest.MonkeyPatch, data: Path, output: Path, during_run: Any, caplog: pytest.LogCaptureFixture) -> None:
    _at(monkeypatch, datetime(2026, 10, 15, 1, 30, tzinfo=TAIPEI))

    def run(*args: Any) -> dict[str, Any]:
        if during_run is not None:
            during_run()
        return {"metrics": {"return_rate": 0.0, "max_drawdown_rate": 0.0, "win_rate": None, "total_pnl": 0.0, "final_value": 1.0, "trade_count": 0}}

    monkeypatch.setattr(backtest_cli, "resolve_codes", lambda value, **kwargs: ([value], None))
    monkeypatch.setattr(backtest_cli, "load_strategy_class", lambda _: type("Strategy", (), {}))
    monkeypatch.setattr(backtest_cli, "run_backtest_pass", run)
    argv = ["backtest_cli", "--strategy", "unused.py", "--codes", "2330", "--data-path", str(data), "--output", str(output)]
    monkeypatch.setattr(sys, "argv", argv)
    if during_run is None:
        backtest_cli.main()
        assert output.exists()
        return
    backtest_cli.main()
    assert output.exists(), "a finished run is saved; the producer write is recorded, not a reason to discard it"
    assert json.loads(output.read_text(encoding="utf-8"))["data"]["inputs_changed_during_run"]
    assert "inputs changed during the run" in caplog.text


def test_fallback_corporate_action_db_is_fingerprinted_and_rechecked(
    live_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from research_core.run_receipt import data_directory_inputs
    from StockProject.engine.data_loader import DataLoader

    data = _nested_data_dir(live_root)
    resolved = DataLoader(data_path=data).corporate_action_db
    assert resolved is not None and resolved == live_root / "corporate_actions.sqlite"
    names = {spec.name: spec.path for spec in data_directory_inputs(data, corporate_actions=resolved)}
    assert names["corporate_actions"] == resolved

    def writer_commits() -> None:
        with closing(sqlite3.connect(resolved)) as database:
            database.execute("INSERT INTO corporate_actions (code, ex_date) VALUES ('2330', '2026-10-15')")
            database.commit()

    _run_with_real_loader(monkeypatch, data, tmp_path / "summary.json", writer_commits, caplog)


def test_first_day_csv_appearing_mid_run_is_recorded(
    live_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data = _nested_data_dir(live_root)
    assert not list(data.glob("*_day.csv"))
    _run_with_real_loader(monkeypatch, data, tmp_path / "summary.json", lambda: (data / "2330_day.csv").write_text("Date,Close\n", encoding="utf-8"), caplog)


def test_optional_input_appearing_mid_run_is_recorded(
    live_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data = _nested_data_dir(live_root)
    _run_with_real_loader(monkeypatch, data, tmp_path / "summary.json", lambda: (data / "dividends.parquet").write_bytes(b"new"), caplog)


def test_unchanged_live_inputs_let_the_backtest_write_results(
    live_root: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Control for the recorded-change cases: the same run with no producer write completes."""
    _run_with_real_loader(monkeypatch, _nested_data_dir(live_root), tmp_path / "summary.json", None, caplog)


def test_comparison_artifacts_carry_inputs_changed_during_the_run() -> None:
    summaries: dict[str, dict[str, Any]] = {"shared": {"data": {"inputs_changed_during_run": ["price_daily"]}}, "per_stock": {"data": {}}}
    assert backtest_cli._with_input_changes({"modes": {}}, summaries) == {"modes": {}, "inputs_changed_during_run": ["price_daily"]}
    assert backtest_cli._with_input_changes({"modes": {}}, {"shared": {"data": {}}}) == {"modes": {}}

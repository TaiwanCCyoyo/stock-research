from pathlib import Path
from typing import Any

import pytest
from pytest import MonkeyPatch

from scripts import stock_research_query
from scripts.stock_research_query import realized_pnl_by_index


def _buy(code: str, qty: int, total: float) -> dict:
    return {"action": "BUY", "code": code, "qty": qty, "total": total}


def _sell(code: str, qty: int, total: float) -> dict:
    return {"action": "SELL", "code": code, "qty": qty, "total": total}


def _split(code: str, new_qty: int) -> dict:
    return {"action": "SPLIT", "code": code, "qty": 0, "new_qty": new_qty, "total": 0}


def _div(code: str, total: float) -> dict:
    return {"action": "DIVIDEND", "code": code, "qty": 0, "total": total}


# ── realized_pnl_by_index ───────────────────────────────────────────────────


def test_realized_pnl_by_index_empty() -> None:
    assert realized_pnl_by_index([]) == {}


def test_realized_pnl_by_index_buy_has_no_pnl() -> None:
    result = realized_pnl_by_index([_buy("2330", 1000, -600_000.0)])
    assert result[0]["realized_pnl"] is None
    assert result[0]["is_add_on"] is False
    assert result[0]["position_before"] == 0


def test_realized_pnl_by_index_sell_profit() -> None:
    """BUY 1000@600 then SELL 1000@700 = profit 100_000."""
    trades = [_buy("2330", 1000, -600_000.0), _sell("2330", 1000, 700_000.0)]
    result = realized_pnl_by_index(trades)
    assert result[1]["realized_pnl"] == pytest.approx(100_000.0)
    assert result[1]["cumulative_realized_pnl"] == pytest.approx(100_000.0)


def test_realized_pnl_by_index_sell_loss() -> None:
    trades = [_buy("2330", 1000, -600_000.0), _sell("2330", 1000, 500_000.0)]
    result = realized_pnl_by_index(trades)
    assert result[1]["realized_pnl"] == pytest.approx(-100_000.0)


def test_realized_pnl_by_index_partial_sell_proportional() -> None:
    """Matches backtest_cli.py calculate_trade_stats proportional basis logic.

    BUY 1000 shares, cost_basis = 600_000.
    SELL 500: sold_basis = 600_000 * (500/1000) = 300_000, pnl = 400_000 - 300_000 = 100_000.
    SELL 500: sold_basis = 300_000 * (500/500) = 300_000, pnl = 250_000 - 300_000 = -50_000.
    """
    trades = [
        _buy("2330", 1000, -600_000.0),
        _sell("2330", 500, 400_000.0),
        _sell("2330", 500, 250_000.0),
    ]
    result = realized_pnl_by_index(trades)
    assert result[1]["realized_pnl"] == pytest.approx(100_000.0)
    assert result[2]["realized_pnl"] == pytest.approx(-50_000.0)
    assert result[2]["cumulative_realized_pnl"] == pytest.approx(50_000.0)


def test_realized_pnl_by_index_add_on_flagged() -> None:
    trades = [_buy("2330", 1000, -600_000.0), _buy("2330", 500, -300_000.0)]
    result = realized_pnl_by_index(trades)
    assert result[0]["is_add_on"] is False
    assert result[1]["is_add_on"] is True


def test_realized_pnl_by_index_split_updates_position() -> None:
    """SPLIT while holding updates running position; next BUY is an add-on."""
    trades = [
        _buy("2330", 1000, -600_000.0),  # position = 1000
        _split("2330", 2000),  # 1:2 split → position = 2000
        _buy("2330", 500, -300_000.0),  # add-on: still holding 2000
    ]
    result = realized_pnl_by_index(trades)
    assert result[2]["is_add_on"] is True
    assert result[2]["position_before"] == 2000


def test_realized_pnl_by_index_fresh_buy_after_full_exit() -> None:
    """BUY after a full SELL exit is not an add-on."""
    trades = [
        _buy("2330", 1000, -600_000.0),
        _sell("2330", 1000, 700_000.0),
        _buy("2330", 1000, -500_000.0),  # fresh position
    ]
    result = realized_pnl_by_index(trades)
    assert result[2]["is_add_on"] is False
    assert result[2]["position_before"] == 0


def test_realized_pnl_by_index_dividend_ignored_for_pnl() -> None:
    """DIVIDEND does not affect cost basis or pnl."""
    trades = [_buy("2330", 1000, -600_000.0), _div("2330", 5_000.0), _sell("2330", 1000, 700_000.0)]
    result = realized_pnl_by_index(trades)
    assert result[2]["realized_pnl"] == pytest.approx(100_000.0)


def test_realized_pnl_by_index_two_codes_independent() -> None:
    """Two different codes track cumulative PnL independently."""
    trades = [
        _buy("2330", 1000, -600_000.0),
        _buy("2454", 1000, -400_000.0),
        _sell("2330", 1000, 700_000.0),
        _sell("2454", 1000, 350_000.0),
    ]
    result = realized_pnl_by_index(trades)
    assert result[2]["realized_pnl"] == pytest.approx(100_000.0)
    assert result[3]["realized_pnl"] == pytest.approx(-50_000.0)
    assert result[2]["cumulative_realized_pnl"] == pytest.approx(100_000.0)
    assert result[3]["cumulative_realized_pnl"] == pytest.approx(-50_000.0)


def test_realized_pnl_by_index_cumulative_accumulates() -> None:
    """Cumulative PnL grows across multiple closed trades for the same code."""
    trades = [
        _buy("2330", 1000, -600_000.0),
        _sell("2330", 1000, 700_000.0),
        _buy("2330", 1000, -600_000.0),
        _sell("2330", 1000, 650_000.0),
    ]
    result = realized_pnl_by_index(trades)
    assert result[1]["cumulative_realized_pnl"] == pytest.approx(100_000.0)
    assert result[3]["cumulative_realized_pnl"] == pytest.approx(150_000.0)


# ── cash_context additions ──────────────────────────────────────────────────


def test_cash_context_cash_after_trade_on_buy() -> None:
    trades = [{"action": "BUY", "code": "2330", "qty": 1000, "price": 600.0, "fee": 855, "tax": 0, "total": -600_855.0}]
    summary: dict[str, Any] = {"run": {"initial_cash": 1_000_000.0}, "trades": trades}
    ctx = stock_research_query.cash_context(summary, 0, trades[0])
    assert ctx["cash_before_trade"] == pytest.approx(1_000_000.0)
    assert ctx["cash_after_trade"] == pytest.approx(1_000_000.0 - 600_855.0)


def test_cash_context_is_add_on_false_for_fresh_buy() -> None:
    trades = [{"action": "BUY", "code": "2330", "qty": 1000, "price": 600.0, "fee": 855, "tax": 0, "total": -600_855.0}]
    summary: dict[str, Any] = {"run": {"initial_cash": 1_000_000.0}, "trades": trades}
    ctx = stock_research_query.cash_context(summary, 0, trades[0])
    assert ctx["is_add_on"] is False


def test_cash_context_is_add_on_true_for_second_buy() -> None:
    trades = [
        {"action": "BUY", "code": "2330", "qty": 1000, "price": 600.0, "fee": 855, "tax": 0, "total": -600_855.0},
        {"action": "BUY", "code": "2330", "qty": 500, "price": 610.0, "fee": 435, "tax": 0, "total": -305_435.0},
    ]
    summary = {"run": {"initial_cash": 2_000_000.0}, "trades": trades}
    ctx = stock_research_query.cash_context(summary, 1, trades[1])
    assert ctx["is_add_on"] is True


def test_cash_context_realized_pnl_on_sell() -> None:
    trades = [
        {"action": "BUY", "code": "2330", "qty": 1000, "price": 600.0, "fee": 0, "tax": 0, "total": -600_000.0},
        {"action": "SELL", "code": "2330", "qty": 1000, "price": 700.0, "fee": 0, "tax": 0, "total": 700_000.0},
    ]
    summary = {"run": {"initial_cash": 1_000_000.0}, "trades": trades}
    ctx = stock_research_query.cash_context(summary, 1, trades[1])
    assert ctx["realized_pnl"] == pytest.approx(100_000.0)
    assert ctx["cumulative_realized_pnl"] == pytest.approx(100_000.0)


def test_cash_context_per_stock_uses_symbol_bucket() -> None:
    trades = [
        {"action": "BUY", "code": "A", "qty": 1, "price": 100.0, "fee": 0, "tax": 0, "total": -100.0},
        {"action": "BUY", "code": "B", "qty": 1, "price": 50.0, "fee": 0, "tax": 0, "total": -50.0},
    ]
    summary = {"run": {"initial_cash": 200.0, "capital_mode": "per_stock", "per_stock_initial_cash": 100.0}, "trades": trades}
    ctx = stock_research_query.cash_context(summary, 1, trades[1])
    assert ctx["cash_before_trade"] == pytest.approx(100.0)
    assert ctx["cash_after_trade"] == pytest.approx(50.0)


def test_inspect_task_trade_accepts_per_mode_summary_file(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "prices").mkdir()
    task_root = tmp_path / "mode_task"
    task_root.mkdir()
    summary_path = task_root / "summary_per_stock.json"
    summary_path.write_text(
        json_dumps({
            "run": {"initial_cash": 200.0, "capital_mode": "per_stock", "per_stock_initial_cash": 100.0},
            "strategy": {"params": {}},
            "data": {"path": str(tmp_path / "prices")},
            "trades": [
                {"date": "2025-01-02", "action": "BUY", "code": "A", "qty": 1, "price": 100.0, "fee": 0, "tax": 0, "total": -100.0},
                {"date": "2025-01-02", "action": "BUY", "code": "B", "qty": 1, "price": 50.0, "fee": 0, "tax": 0, "total": -50.0},
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(stock_research_query, "TASKS_ROOT", tmp_path)
    monkeypatch.setattr(
        stock_research_query,
        "load_price_data",
        lambda data_path, code: make_price_frame(code),
    )

    report = stock_research_query.inspect_task_trade("mode_task", trade_id="T002", summary_file="summary_per_stock.json")

    assert report["cash_context"]["cash_before_trade"] == pytest.approx(100.0)
    assert report["cash_context"]["cash_after_trade"] == pytest.approx(50.0)


def test_list_task_trades_reads_per_mode_summary_file(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    task_root = tmp_path / "mode_task"
    task_root.mkdir()
    (task_root / "summary.json").write_text(json_dumps({"trades": []}), encoding="utf-8")
    (task_root / "summary_per_stock.json").write_text(
        json_dumps({
            "trades": [
                {"date": "2025-01-02", "action": "BUY", "code": "A", "qty": 1, "price": 100.0, "total": -100.0},
            ],
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(stock_research_query, "TASKS_ROOT", tmp_path)

    result = stock_research_query.list_task_trades("mode_task", summary_file="summary_per_stock.json")

    assert result["count"] == 1
    assert result["trades"][0]["code"] == "A"
    assert result["query"]["summary_file"] == "summary_per_stock.json"


def test_list_task_trades_missing_summary_file_raises(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    task_root = tmp_path / "mode_task"
    task_root.mkdir()
    (task_root / "summary.json").write_text(json_dumps({"trades": []}), encoding="utf-8")
    monkeypatch.setattr(stock_research_query, "TASKS_ROOT", tmp_path)

    with pytest.raises(stock_research_query.QueryError):
        stock_research_query.list_task_trades("mode_task", summary_file="summary_shared.json")


def json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, indent=4)


def make_price_frame(code: str | None):
    import pandas as pd

    return pd.DataFrame([
        {
            "Date": pd.Timestamp("2025-01-02"),
            "Code": code,
            "Open": 10.0,
            "High": 12.0,
            "Low": 9.0,
            "Close": 11.0,
        }
    ])


def write_price_csv(data_root: Path, code: str = "2352") -> None:
    data_root.mkdir(parents=True)
    (data_root / f"{code}_day.csv").write_text(
        "Date,Open,High,Low,Close\n2025-01-02,10,12,9,11\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize("trade_date", [None, ""])
def test_price_context_rejects_missing_trade_date(trade_date: str | None) -> None:
    import pandas as pd

    with pytest.raises(stock_research_query.QueryError, match="trade date is required"):
        stock_research_query.price_context(pd.DataFrame(), trade_date, {})


def test_load_price_data_reads_only_requested_symbol_file(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """A single-symbol load must not scan every *_day.csv in the data directory."""
    import os

    import pandas as pd

    data_root = tmp_path / "prices"
    write_price_csv(data_root, "2352")
    (data_root / "2330_day.csv").write_text(
        "Date,Open,High,Low,Close\n2025-01-02,100,102,99,101\n",
        encoding="utf-8",
    )

    read_paths: list[str] = []
    original_read_csv = pd.read_csv

    def spy_read_csv(path: object, *args: object, **kwargs: object) -> pd.DataFrame:
        read_paths.append(os.path.basename(str(path)))
        return original_read_csv(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(pd, "read_csv", spy_read_csv)

    df = stock_research_query.load_price_data(data_root, "2352")

    assert read_paths == ["2352_day.csv"]
    assert df.iloc[0]["Code"] == "2352"
    assert df.iloc[0]["Close"] == 11


def test_load_price_data_rejects_stale_path_instead_of_using_current_data(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    fallback_root = tmp_path / "repo" / "shioaji_stock_prices" / "data"
    write_price_csv(fallback_root)
    stale_root = tmp_path / "old-machine" / "shioaji_stock_prices" / "data"
    monkeypatch.setattr(stock_research_query, "DEFAULT_DATA_PATH", fallback_root)

    with pytest.raises(stock_research_query.QueryError, match="no automatic fallback"):
        stock_research_query.load_price_data(stale_root, "2352")


def test_explicit_price_override_reports_actual_path_and_unverified_provenance(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    task = tmp_path / "task"
    task.mkdir()
    original = str(tmp_path / "missing")
    (task / "summary.json").write_text(
        json_dumps({"data": {"path": original}, "trades": [{"action": "BUY", "code": "2352", "date": "2025-01-02"}]}), encoding="utf-8"
    )
    override = tmp_path / "override"
    write_price_csv(override)
    monkeypatch.setattr(stock_research_query, "TASKS_ROOT", tmp_path)
    report = stock_research_query.inspect_task_trade("task", trade_id="T001", data_path=override)
    assert report["data_path"] == str(override.resolve())
    assert report["data_provenance"]["recorded_path"] == original
    assert report["data_provenance"]["mode"] == "explicit_override"
    assert report["data_provenance"]["snapshot_verified"] is False


def test_relative_data_path_is_repo_relative_not_cwd(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "snapshot").mkdir()
    monkeypatch.setattr(stock_research_query, "REPO_ROOT", tmp_path)
    assert stock_research_query.resolve_price_data_root("snapshot") == tmp_path / "snapshot"


@pytest.mark.parametrize("recorded", [None, "", " ", 5, {}])
def test_absent_or_malformed_snapshot_never_falls_back(monkeypatch: MonkeyPatch, tmp_path: Path, recorded: Any) -> None:
    monkeypatch.setattr(stock_research_query, "DEFAULT_DATA_PATH", tmp_path)
    with pytest.raises(stock_research_query.QueryError, match="explicit data-path override"):
        stock_research_query.resolve_price_data_root(recorded)


def test_task_list_includes_report_only_without_parsing_economics(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    task = tmp_path / "report-only"
    task.mkdir()
    (task / "report.md").write_text("Already published report", encoding="utf-8")
    monkeypatch.setattr(stock_research_query, "TASKS_ROOT", tmp_path)
    item = stock_research_query.list_research_tasks()["tasks"][0]
    assert item["task"] == "report-only"
    assert item["report"] is True
    assert item["summary"] is False
    assert item["outcome"] == "unknown"


@pytest.mark.parametrize("query", [stock_research_query.inspect_task_trade, stock_research_query.list_task_trades])
def test_shared_queries_reject_summary_escape(monkeypatch: MonkeyPatch, tmp_path: Path, query: Any) -> None:
    (tmp_path / "task").mkdir()
    (tmp_path / "outside.json").write_text('{"trades": []}', encoding="utf-8")
    monkeypatch.setattr(stock_research_query, "TASKS_ROOT", tmp_path)
    with pytest.raises(stock_research_query.QueryError, match="inside the task"):
        query("task", summary_file="../outside.json")

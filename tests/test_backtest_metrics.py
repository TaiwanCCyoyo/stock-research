"""Tests for calculate_trade_stats extended pnl statistics."""

from pathlib import Path

from pytest import MonkeyPatch

from StockProject.backtest_cli import artifact_path, calculate_trade_stats


def _make_buy(code: str, qty: int, total: float) -> dict:
    return {"action": "BUY", "code": code, "qty": qty, "total": total}


def _make_sell(code: str, qty: int, total: float) -> dict:
    return {"action": "SELL", "code": code, "qty": qty, "total": total}


def test_trade_stats_with_wins_and_losses() -> None:
    """Mixed win and loss trades produce correct per-trade pnl statistics.

    BUY 1000 shares, cost_basis becomes 600000 (total=-600000, basis -= -600000 = +600000).
    SELL 500 shares: sold_basis = 600000 * (500/1000) = 300000, pnl = 400000 - 300000 = 100000 (win).
    SELL 500 shares: sold_basis = 300000 * (500/500) = 300000, pnl = 250000 - 300000 = -50000 (loss).
    """
    trades = [
        _make_buy("2330", 1000, -600000.0),
        _make_sell("2330", 500, 400000.0),
        _make_sell("2330", 500, 250000.0),
    ]
    result = calculate_trade_stats(trades)

    assert result["closed_trade_count"] == 2
    assert result["win_count"] == 1
    assert result["win_rate"] == 50.0

    assert result["avg_win"] == 100000.0
    assert result["avg_loss"] == -50000.0
    assert result["payoff_ratio"] == 2.0
    assert result["expectancy"] == 25000.0
    assert result["gross_profit"] == 100000.0
    assert result["gross_loss"] == -50000.0
    assert result["profit_factor"] == 2.0
    assert result["largest_win"] == 100000.0
    assert result["largest_loss"] == -50000.0


def test_trade_stats_no_closed_trades() -> None:
    """Only BUY trades: all new statistics are None, existing fields are zero/None."""
    trades = [
        _make_buy("2330", 1000, -600000.0),
    ]
    result = calculate_trade_stats(trades)

    assert result["closed_trade_count"] == 0
    assert result["win_count"] == 0
    assert result["win_rate"] is None

    assert result["avg_win"] is None
    assert result["avg_loss"] is None
    assert result["payoff_ratio"] is None
    assert result["expectancy"] is None
    assert result["gross_profit"] is None
    assert result["gross_loss"] is None
    assert result["profit_factor"] is None
    assert result["largest_win"] is None
    assert result["largest_loss"] is None


def test_trade_stats_all_wins() -> None:
    """All profitable SELL trades: loss-side statistics are None."""
    trades = [
        _make_buy("2330", 1000, -600000.0),
        _make_sell("2330", 500, 400000.0),
        _make_sell("2330", 500, 350000.0),
    ]
    result = calculate_trade_stats(trades)

    assert result["closed_trade_count"] == 2
    assert result["win_count"] == 2
    assert result["avg_win"] is not None
    assert result["gross_profit"] is not None
    assert result["largest_win"] is not None

    assert result["avg_loss"] is None
    assert result["payoff_ratio"] is None
    assert result["gross_loss"] is None
    assert result["largest_loss"] is None
    assert result["profit_factor"] is None


def test_trade_stats_all_losses() -> None:
    """All losing SELL trades: win-side statistics are None."""
    trades = [
        _make_buy("2330", 1000, -600000.0),
        _make_sell("2330", 500, 200000.0),
        _make_sell("2330", 500, 100000.0),
    ]
    result = calculate_trade_stats(trades)

    assert result["closed_trade_count"] == 2
    assert result["win_count"] == 0
    assert result["avg_loss"] is not None
    assert result["gross_loss"] is not None
    assert result["largest_loss"] is not None

    assert result["avg_win"] is None
    assert result["payoff_ratio"] is None
    assert result["gross_profit"] is None
    assert result["largest_win"] is None
    assert result["profit_factor"] is None


def test_trade_stats_existing_fields_unchanged() -> None:
    """Regression: closed_trade_count, win_count, win_rate match pre-extension behaviour."""
    trades = [
        _make_buy("2330", 500, -300000.0),
        _make_sell("2330", 500, 350000.0),
        _make_buy("2412", 200, -100000.0),
        _make_sell("2412", 200, 80000.0),
    ]
    result = calculate_trade_stats(trades)

    assert result["closed_trade_count"] == 2
    assert result["win_count"] == 1
    assert result["win_rate"] == 50.0


def test_trade_stats_break_even_trade() -> None:
    """A break-even trade (pnl == 0) is counted as a closed trade and placed in losses.

    BUY 1000 shares, cost_basis becomes 600000 (total=-600000).
    SELL 1000 shares at total=600000: sold_basis = 600000, pnl = 600000 - 600000 = 0.
    Expected: closed_trade_count=1, win_count=0, losses=[0.0], expectancy=0.0.
    """
    trades = [
        _make_buy("2330", 1000, -600000.0),
        _make_sell("2330", 1000, 600000.0),
    ]
    result = calculate_trade_stats(trades)

    assert result["closed_trade_count"] == 1
    assert result["win_count"] == 0
    assert result["win_rate"] == 0.0
    assert result["avg_loss"] == 0.0
    assert result["gross_loss"] == 0.0
    assert result["largest_loss"] == 0.0
    assert result["expectancy"] == 0.0
    assert result["avg_win"] is None
    assert result["gross_profit"] is None
    assert result["largest_win"] is None


def test_artifact_path_prefers_relative_paths(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    data_path = tmp_path / "stock-data-downloader" / "data" / "adjusted_prices" / "daily"

    assert artifact_path(data_path) == "stock-data-downloader/data/adjusted_prices/daily"
    assert artifact_path(data_path / "price_daily.parquet") == "stock-data-downloader/data/adjusted_prices/daily/price_daily.parquet"
